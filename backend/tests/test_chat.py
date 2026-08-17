import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import ChatMessage, ChatRole, Document, DocumentStatus, GoalType, Notebook, Overview, OverviewStatus
from app.services.chat import ask_question, edit_question
from app.services.embeddings import embed_texts
from app.services.vector_store import VectorStore

ML_TEXTS = [
    "Machine learning is a subset of artificial intelligence focused on building systems that learn from data.",
    "Supervised learning uses labeled data while unsupervised learning finds patterns without labels.",
    "Neural networks consist of layers of nodes with weights updated during training via backpropagation.",
]


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def vector_store(tmp_path) -> VectorStore:
    return VectorStore(persist_dir=tmp_path / "chroma", collection_name="chat_test")


class ScriptedTextClient:
    """Returns each response in order, one per call to generate_text."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


async def _create_notebook(session: AsyncSession, **kwargs) -> Notebook:
    notebook = Notebook(**kwargs)
    session.add(notebook)
    await session.commit()
    await session.refresh(notebook)
    return notebook


async def _add_ready_document(
    session: AsyncSession,
    vector_store: VectorStore,
    notebook_id: str,
    filename: str,
    texts: list[str],
    pages: list[int] | None = None,
) -> Document:
    doc = Document(
        notebook_id=notebook_id, filename=filename, file_path="/tmp/x.pdf", status=DocumentStatus.READY
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    pages = pages or [1] * len(texts)
    chunk_ids = [str(uuid.uuid4()) for _ in texts]
    vector_store.add(
        document_id=doc.id,
        chunk_ids=chunk_ids,
        texts=texts,
        embeddings=embed_texts(texts),
        page_numbers=pages,
    )
    return doc


async def _add_ready_overview(session: AsyncSession, notebook_id: str, short_summary: str) -> Overview:
    overview = Overview(notebook_id=notebook_id, status=OverviewStatus.READY, short_summary=short_summary)
    session.add(overview)
    await session.commit()
    await session.refresh(overview)
    return overview


async def _messages_for(session: AsyncSession, notebook_id: str) -> list[ChatMessage]:
    result = await session.execute(
        select(ChatMessage).where(ChatMessage.notebook_id == notebook_id).order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())


class TestGroundedAnswers:
    async def test_relevant_question_is_grounded_with_citations(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["Neural networks learn via backpropagation."])

        reply = await ask_question(
            notebook, "How are neural networks trained?", False, session, vector_store, client
        )

        assert reply.role == ChatRole.ASSISTANT
        assert reply.grounded is True
        assert reply.used_internet is False
        assert reply.content == "Neural networks learn via backpropagation."
        assert len(client.prompts) == 1
        assert "backpropagation" in client.prompts[0].lower()

        messages = await _messages_for(session, notebook.id)
        assert [m.role for m in messages] == [ChatRole.USER, ChatRole.ASSISTANT]
        assert messages[0].content == "How are neural networks trained?"

    async def test_citations_reference_the_source_document_and_page(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        doc = await _add_ready_document(
            session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3]
        )
        client = ScriptedTextClient(["An answer."])

        reply = await ask_question(
            notebook, "What is machine learning?", False, session, vector_store, client
        )

        from app.schemas import ChatMessageRead

        read = ChatMessageRead.from_model(reply)
        assert len(read.citations) > 0
        assert read.citations[0].document_id == doc.id
        assert read.citations[0].filename == "ml.pdf"
        assert read.citations[0].page_number is not None

    async def test_citations_and_excerpts_exclude_irrelevant_retrieved_chunks(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """Regression test: retrieval returns top_k chunks, and only the best
        one needs to clear the relevance bar for the answer to count as
        grounded — but every retrieved chunk used to get fed into the prompt
        and cited regardless, so a grounded answer could still cite (or be
        prompted with) a completely unrelated chunk, e.g. a biology answer
        citing a page about basketball."""
        notebook = await _create_notebook(session, name="Mixed Notes")
        relevant_text = (
            "Mitochondria are the powerhouse of the cell, producing ATP through cellular respiration."
        )
        unrelated_texts = [
            "The point guard dribbled past two defenders and scored a three-pointer.",
            "The French Revolution began in 1789 and led to the end of the monarchy.",
            "Stock prices fluctuate based on supply, demand, and investor sentiment.",
            "A good pizza dough needs flour, water, yeast, and salt.",
            "The Amazon rainforest produces roughly 20% of the world's oxygen.",
        ]
        await _add_ready_document(session, vector_store, notebook.id, "biology.pdf", [relevant_text], [1])
        await _add_ready_document(
            session, vector_store, notebook.id, "misc.pdf", unrelated_texts, [1, 2, 3, 4, 5]
        )
        client = ScriptedTextClient(["Mitochondria produce ATP."])

        reply = await ask_question(
            notebook, "How does a mitochondria produce energy?", False, session, vector_store, client
        )

        assert reply.grounded is True
        from app.schemas import ChatMessageRead

        read = ChatMessageRead.from_model(reply)
        assert len(read.citations) > 0
        assert all(c.filename == "biology.pdf" for c in read.citations)

        prompt = client.prompts[0]
        for unrelated in unrelated_texts:
            assert unrelated not in prompt

    async def test_internet_mode_on_but_grounded_still_uses_material_and_flags_not_used_internet(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """A relevant match means the material already answers the question,
        so internet mode being on doesn't change grounding — used_internet
        only describes answers that actually leaned on general knowledge."""
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["An answer."])

        reply = await ask_question(
            notebook, "What is machine learning?", True, session, vector_store, client
        )

        assert reply.grounded is True
        assert reply.used_internet is False
        assert "beyond your notes" in client.prompts[0].lower()

    async def test_a_distance_threshold_false_positive_is_not_shown_as_grounded(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """Regression test: retrieval can return a chunk that clears the
        distance threshold (numerically "close enough") without actually
        being relevant to the question — e.g. a Python-looping question
        against a notebook that only covers combinatorial software testing.
        When the model notices the mismatch and says so in its own answer,
        that must override the retrieval signal: no citations, no grounded
        badge, on what is really a refusal, not a sourced answer."""
        notebook = await _create_notebook(session, name="Software Testing Fundamentals")
        await _add_ready_document(
            session,
            vector_store,
            notebook.id,
            "week11.pdf",
            ["Combinatorial testing and equivalence partitioning reduce the number of test cases."],
            pages=[2],
        )
        client = ScriptedTextClient(
            [
                "The provided excerpts do not contain any information about Python looping. "
                "The excerpts discuss combinatorial testing, which is unrelated to Python "
                "looping concepts."
            ]
        )

        reply = await ask_question(notebook, "What is python looping", False, session, vector_store, client)

        assert reply.grounded is False
        assert reply.citations_json is None
        assert "do not contain" in reply.content.lower()

    async def test_a_partially_grounded_answer_keeps_its_citations(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """The refusal check only looks at the start of the answer, so a
        substantive answer that leads with real material and only later
        notes a gap keeps its citations — it's not a pure refusal."""
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(
            [
                "Backpropagation adjusts weights using the gradient of the loss function. "
                "The excerpts do not contain details about learning rate schedules, though."
            ]
        )

        reply = await ask_question(
            notebook, "How does backpropagation work?", False, session, vector_store, client
        )

        assert reply.grounded is True
        assert reply.citations_json is not None


class TestUngroundedAnswers:
    async def test_same_domain_different_subtopic_question_is_not_grounded_by_retrieval_alone(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """Regression test for the recalibrated relevance threshold (was
        1.3, now 1.15): a same-broad-domain (both CS-adjacent) but
        substantively unrelated question used to slip under the old, looser
        threshold on vector distance alone — a Python-looping question
        retrieving combinatorial-testing material, exactly the reported bug.
        Checks that retrieval itself now excludes it, independent of the
        model's own refusal wording (see TestGroundedAnswers's
        distance-threshold-false-positive test for that separate safety net)."""
        notebook = await _create_notebook(session, name="Software Testing Fundamentals")
        await _add_ready_document(
            session,
            vector_store,
            notebook.id,
            "week11.pdf",
            [
                "Combinatorial testing and equivalence partitioning reduce the number of "
                "test cases needed to validate software with multiple input parameters."
            ],
            pages=[2],
        )
        await _add_ready_overview(session, notebook.id, "This covers software testing techniques.")
        client = ScriptedTextClient(["Python uses for and while loops to repeat code."])

        reply = await ask_question(notebook, "What is python looping", False, session, vector_store, client)

        assert reply.grounded is False
        assert reply.citations_json is None

    async def test_irrelevant_question_without_internet_mode_still_gets_a_real_answer(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """Regression test: there used to be a fixed canned-string reply for
        this case that never called the LLM. That was too strict — it also
        caught greetings and general "what's this about" questions, which
        aren't factual claims to hallucinate, just things the notebook's own
        overview already answers. The LLM is now always called, given the
        overview as context, and told to be honest if a specific fact truly
        isn't covered."""
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        await _add_ready_overview(session, notebook.id, "This covers machine learning fundamentals.")
        client = ScriptedTextClient(["I don't see a pizza dough recipe in your material."])

        reply = await ask_question(
            notebook, "What's the best pizza dough recipe?", False, session, vector_store, client
        )

        assert reply.content == "I don't see a pizza dough recipe in your material."
        assert reply.grounded is False
        assert reply.used_internet is False
        assert reply.citations_json is None
        assert len(client.prompts) == 1
        assert "machine learning fundamentals" in client.prompts[0].lower()
        assert "isn't covered in your uploaded material" in client.prompts[0].lower()

    async def test_irrelevant_question_with_internet_mode_answers_from_general_knowledge(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["Pizza dough needs flour, water, yeast, and salt."])

        reply = await ask_question(
            notebook, "What's the best pizza dough recipe?", True, session, vector_store, client
        )

        assert reply.grounded is False
        assert reply.used_internet is True
        assert reply.content == "Pizza dough needs flour, water, yeast, and salt."
        assert reply.citations_json is None
        assert "general knowledge" in client.prompts[0].lower()

    async def test_notebook_with_no_ready_documents_and_no_internet_mode_never_calls_the_llm(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        """Regression test: this used to always call the LLM, even with zero
        documents uploaded — the small local model turned out not to reliably
        follow "don't answer from your own knowledge" instructions, so a
        question like "what is MongoDB?" got a confident, fully-fabricated
        answer despite there being no material and internet mode off. The
        only fix that actually guarantees this can't happen is not calling
        the LLM at all for this exact, fully deterministic state."""
        notebook = await _create_notebook(session, name="Empty Notebook")
        client = ScriptedTextClient([])

        reply = await ask_question(notebook, "What is MongoDB?", False, session, vector_store, client)

        assert reply.grounded is False
        assert reply.used_internet is False
        assert "doesn't have any documents yet" in reply.content.lower()
        assert client.prompts == []

    async def test_notebook_with_no_ready_documents_but_internet_mode_still_answers(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="Empty Notebook")
        client = ScriptedTextClient(["MongoDB is a NoSQL database."])

        reply = await ask_question(notebook, "What is MongoDB?", True, session, vector_store, client)

        assert reply.content == "MongoDB is a NoSQL database."
        assert reply.grounded is False
        assert reply.used_internet is True
        assert len(client.prompts) == 1

    async def test_overview_is_included_as_context_when_no_specific_passage_matches(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        await _add_ready_overview(
            session, notebook.id, "This notebook covers supervised and unsupervised learning."
        )
        client = ScriptedTextClient(["This notebook covers machine learning topics."])

        reply = await ask_question(
            notebook, "What is this notebook generally about?", False, session, vector_store, client
        )

        assert reply.grounded is False
        assert "supervised and unsupervised learning" in client.prompts[0].lower()


class TestConversationHistory:
    async def test_follow_up_question_includes_prior_turn_in_the_prompt(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["First answer.", "Second answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)
        await ask_question(
            notebook, "How is that different from deep learning?", False, session, vector_store, client
        )

        second_prompt = client.prompts[1]
        assert "what is machine learning?" in second_prompt.lower()
        assert "first answer." in second_prompt.lower()


class TestGoalAwarePrompting:
    async def test_exam_goal_shapes_the_prompt(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes", goal_type=GoalType.EXAM)
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["An answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)

        assert "prepare for an exam" in client.prompts[0].lower()

    async def test_custom_goal_includes_the_description(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(
            session, name="ML Notes", goal_type=GoalType.CUSTOM, goal_description="Building a side project"
        )
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["An answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)

        assert "building a side project" in client.prompts[0].lower()

    async def test_no_goal_omits_goal_language_from_the_prompt(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["An answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)

        assert "the user's goal" not in client.prompts[0].lower()
        assert "the user is" not in client.prompts[0].lower()


class TestEditQuestion:
    async def test_edit_replaces_the_question_and_discards_everything_after_it(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["First answer.", "Second answer.", "Edited answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)
        await ask_question(
            notebook, "How is that different from deep learning?", False, session, vector_store, client
        )
        messages = await _messages_for(session, notebook.id)
        assert len(messages) == 4
        target = messages[0]  # "What is machine learning?"

        reply = await edit_question(
            notebook, target, "What is supervised learning?", False, session, vector_store, client
        )

        assert reply.content == "Edited answer."
        remaining = await _messages_for(session, notebook.id)
        assert [m.content for m in remaining] == ["What is supervised learning?", "Edited answer."]

    async def test_edit_history_only_includes_turns_before_the_edited_message(
        self, session: AsyncSession, vector_store: VectorStore
    ) -> None:
        notebook = await _create_notebook(session, name="ML Notes")
        await _add_ready_document(session, vector_store, notebook.id, "ml.pdf", ML_TEXTS, pages=[1, 2, 3])
        client = ScriptedTextClient(["First answer.", "Second answer.", "Edited answer."])

        await ask_question(notebook, "What is machine learning?", False, session, vector_store, client)
        messages = await _messages_for(session, notebook.id)
        second_target_index = len(messages)  # points at the next user message, added below
        await ask_question(
            notebook, "How is that different from deep learning?", False, session, vector_store, client
        )
        messages = await _messages_for(session, notebook.id)
        target = messages[second_target_index]  # "How is that different from deep learning?"

        await edit_question(notebook, target, "What is unsupervised learning?", False, session, vector_store, client)

        edited_prompt = client.prompts[-1]
        assert "what is unsupervised learning?" in edited_prompt.lower()
        assert "first answer." in edited_prompt.lower()  # prior turn kept
        assert "how is that different from deep learning?" not in edited_prompt.lower()  # discarded turn

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, DocumentStatus, Notebook, Quiz, QuizStatus
from app.schemas import QuizDifficulty, QuizGenerateRequest, QuizQuestionResult
from app.services.ollama_client import OllamaUnreachableError
from app.services.quiz_generation import _has_duplicate_options, generate_quiz


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class ScriptedClient:
    """Returns each response in order, one per call to generate_json."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        self.calls.append(prompt)
        return self._responses.pop(0)


class UnreachableClient:
    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise OllamaUnreachableError("connection refused")


def _question(text: str = "Q?", correct_index: int = 0, options: list[str] | None = None) -> dict:
    return {
        "question": text,
        "options": options or ["A", "B", "C", "D"],
        "correct_index": correct_index,
        "explanation": "Because.",
    }


async def _create_notebook_with_ready_document(
    session: AsyncSession, chunk_texts: list[str], notebook_name: str = "Test Notebook"
) -> Notebook:
    notebook = Notebook(name=notebook_name)
    session.add(notebook)
    await session.flush()
    doc = Document(
        notebook_id=notebook.id,
        filename="notes.pdf",
        file_path="/tmp/notes.pdf",
        status=DocumentStatus.READY,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    for i, text in enumerate(chunk_texts):
        session.add(Chunk(document_id=doc.id, chunk_index=i, text=text, page_number=1))
    await session.commit()
    return notebook


async def _get_quiz_row(session: AsyncSession, notebook_id: str) -> Quiz | None:
    result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
    return result.scalar_one_or_none()


class TestHasDuplicateOptions:
    """Regression coverage for the reported bug: a question offering both
    "Llama" and "LLaMA" as separate options, with one arbitrarily marked
    correct and the other arbitrarily marked wrong — the user picking the
    "wrong" one was actually picking a correct answer spelled differently."""

    def test_same_word_different_capitalization_is_a_duplicate(self) -> None:
        q = QuizQuestionResult(**_question(options=["Llama", "Mistral", "LLaMA", "GPT"]))
        assert _has_duplicate_options(q) is True

    def test_same_phrase_with_extra_whitespace_or_punctuation_is_a_duplicate(self) -> None:
        q = QuizQuestionResult(**_question(options=["Self-Supervised Learning", "A", "B", "self supervised learning"]))
        assert _has_duplicate_options(q) is True

    def test_four_genuinely_different_options_is_not_a_duplicate(self) -> None:
        q = QuizQuestionResult(**_question(options=["Mistral", "Llama", "GPT-4", "Gemini"]))
        assert _has_duplicate_options(q) is False


class TestGenerateQuiz:
    async def test_success_produces_ready_quiz_with_questions(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some study content about biology."])
        notebook_id = notebook.id
        response = json.dumps({"questions": [_question("What is a cell?"), _question("What is DNA?", 2)]})
        client = ScriptedClient([response])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.READY
        questions = json.loads(row.questions_json)
        assert len(questions) == 2
        assert questions[0]["question"] == "What is a cell?"
        assert questions[1]["correct_index"] == 2

    async def test_a_question_with_duplicate_options_is_dropped_not_shown(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some study content about LLMs."])
        notebook_id = notebook.id
        response = json.dumps(
            {
                "questions": [
                    _question("Good question?"),
                    _question(
                        "Which LLM family?",
                        correct_index=2,
                        options=["Mistral", "Llama", "LLaMA", "GPT"],
                    ),
                ]
            }
        )
        client = ScriptedClient([response])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.READY
        questions = json.loads(row.questions_json)
        assert len(questions) == 1
        assert questions[0]["question"] == "Good question?"

    async def test_creates_the_quiz_row_itself_when_none_exists_yet(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        assert await _get_quiz_row(session, notebook_id) is None
        client = ScriptedClient([json.dumps({"questions": [_question()]})])

        await generate_quiz(notebook_id, session, client)

        assert await _get_quiz_row(session, notebook_id) is not None

    async def test_llm_unreachable_marks_quiz_failed(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id

        await generate_quiz(notebook_id, session, UnreachableClient())

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.FAILED
        assert row.error_reason == "llm_unreachable"

    async def test_invalid_llm_response_marks_quiz_failed_after_retrying(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient(["not json", "still not json"])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.FAILED
        assert row.error_reason == "invalid_llm_response"
        assert len(client.calls) == 2  # MAX_RETRIES

    async def test_retries_once_and_succeeds_on_the_second_attempt(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        good = json.dumps({"questions": [_question()]})
        client = ScriptedClient(["not json", good])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.READY

    async def test_question_count_is_capped_at_the_requested_target(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps(
            {"questions": [_question("Q1"), _question("Q2"), _question("Q3"), _question("Q4")]}
        )
        client = ScriptedClient([response])

        await generate_quiz(notebook_id, session, client, options=QuizGenerateRequest(question_count=3))

        row = await _get_quiz_row(session, notebook_id)
        questions = json.loads(row.questions_json)
        assert len(questions) == 3

    async def test_default_question_count_matches_the_settings_default(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps({"questions": [_question(f"Q{i}") for i in range(10)]})
        client = ScriptedClient([response])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        questions = json.loads(row.questions_json)
        assert len(questions) == 8  # QuizGenerateRequest's default question_count

    async def test_difficulty_and_focus_and_general_knowledge_reach_the_prompt(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient([json.dumps({"questions": [_question()]})])

        await generate_quiz(
            notebook_id,
            session,
            client,
            options=QuizGenerateRequest(
                difficulty=QuizDifficulty.HARD,
                allow_general_knowledge=True,
                focus="chapter 3",
            ),
        )

        prompt = client.calls[0].lower()
        assert "reasoning about the material" in prompt  # hard-difficulty clause
        assert "own general knowledge" in prompt  # general-knowledge clause

    async def test_prompt_forbids_the_same_answer_listed_twice_under_different_spelling(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient([json.dumps({"questions": [_question()]})])

        await generate_quiz(notebook_id, session, client)

        prompt = client.calls[0].lower()
        assert "never list the same real-world" in prompt

    async def test_combines_chunks_from_multiple_documents_in_the_notebook(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.flush()
        doc_a = Document(
            notebook_id=notebook.id, filename="a.pdf", file_path="/tmp/a.pdf", status=DocumentStatus.READY
        )
        doc_b = Document(
            notebook_id=notebook.id, filename="b.pdf", file_path="/tmp/b.pdf", status=DocumentStatus.READY
        )
        session.add_all([doc_a, doc_b])
        await session.commit()
        await session.refresh(doc_a)
        await session.refresh(doc_b)
        session.add(Chunk(document_id=doc_a.id, chunk_index=0, text="unique-marker-from-a", page_number=1))
        session.add(Chunk(document_id=doc_b.id, chunk_index=0, text="unique-marker-from-b", page_number=1))
        await session.commit()
        notebook_id = notebook.id

        response = json.dumps({"questions": [_question()]})
        client = ScriptedClient([response])

        await generate_quiz(notebook_id, session, client)

        assert "unique-marker-from-a" in client.calls[0]
        assert "unique-marker-from-b" in client.calls[0]
        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.READY

    async def test_notebook_with_no_ready_documents_fails_with_no_content(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Empty Notebook")
        session.add(notebook)
        await session.commit()
        await session.refresh(notebook)
        notebook_id = notebook.id
        client = ScriptedClient([])

        await generate_quiz(notebook_id, session, client)

        row = await _get_quiz_row(session, notebook_id)
        assert row.status == QuizStatus.FAILED
        assert row.error_reason == "no_content"

import asyncio
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, DocumentStatus, Notebook, Overview, OverviewStatus
from app.services.ollama_client import OllamaUnreachableError
from app.services.overview_generation import _build_sections, generate_overview


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _chunk(text: str, index: int) -> Chunk:
    return Chunk(id=f"chunk-{index}", document_id="doc-1", chunk_index=index, text=text, page_number=1)


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


class TestBuildSections:
    def test_small_document_returns_a_single_section(self) -> None:
        chunks = [_chunk("A short chunk of text.", 0)]
        sections = _build_sections(chunks)
        assert len(sections) == 1
        assert sections[0] == "A short chunk of text."

    def test_large_document_splits_into_bounded_sections(self) -> None:
        # ~40,000 chars total, well over the single-pass budget and the target
        # per-section size, so this should hit the max-section cap, not one
        # section per chunk.
        chunks = [_chunk("word " * 200, i) for i in range(40)]
        sections = _build_sections(chunks)
        assert 1 < len(sections) <= 8

    def test_sections_together_cover_the_whole_document(self) -> None:
        chunks = [_chunk(f"unique-marker-{i} " * 100, i) for i in range(20)]
        sections = _build_sections(chunks)
        combined = "\n\n".join(sections)
        for i in range(20):
            assert f"unique-marker-{i}" in combined

    def test_empty_chunk_list_returns_no_sections(self) -> None:
        assert _build_sections([]) == []


async def _get_overview_row(session: AsyncSession, notebook_id: str) -> Overview | None:
    result = await session.execute(select(Overview).where(Overview.notebook_id == notebook_id))
    return result.scalar_one_or_none()


class TestGenerateOverview:
    async def test_success_produces_ready_overview_with_topics(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some study content about biology."]
        )
        response = json.dumps(
            {
                "short_summary": "A short summary of cell biology.",
                "topics": [
                    {"title": "Cell Biology", "summary": "Covers cell structure.", "key_concepts": ["nucleus"]}
                ],
                "estimated_minutes": 15,
            }
        )
        client = ScriptedClient([response])

        await generate_overview(notebook.id, session, client)

        row = await _get_overview_row(session, notebook.id)
        assert row.status == OverviewStatus.READY
        assert row.estimated_minutes == 15
        assert row.short_summary == "A short summary of cell biology."
        topics = json.loads(row.topics_json)
        assert topics[0]["title"] == "Cell Biology"

    async def test_synthesis_response_missing_short_summary_is_invalid(
        self, session: AsyncSession
    ) -> None:
        """short_summary is required in the LLM's response, same as topics —
        a response missing it is treated as an invalid LLM response and
        retried, not silently accepted with an empty summary."""
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        malformed = json.dumps(
            {"topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient([malformed, malformed])

        await generate_overview(notebook_id, session, client)

        row = await _get_overview_row(session, notebook_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "invalid_llm_response"

    async def test_combines_chunks_from_multiple_documents_in_the_notebook(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.flush()
        doc_a = Document(
            notebook_id=notebook.id,
            filename="a.pdf",
            file_path="/tmp/a.pdf",
            status=DocumentStatus.READY,
        )
        doc_b = Document(
            notebook_id=notebook.id,
            filename="b.pdf",
            file_path="/tmp/b.pdf",
            status=DocumentStatus.READY,
        )
        session.add_all([doc_a, doc_b])
        await session.commit()
        await session.refresh(doc_a)
        await session.refresh(doc_b)
        session.add(Chunk(document_id=doc_a.id, chunk_index=0, text="unique-marker-from-a", page_number=1))
        session.add(Chunk(document_id=doc_b.id, chunk_index=0, text="unique-marker-from-b", page_number=1))
        await session.commit()

        response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient([response])

        await generate_overview(notebook.id, session, client)

        assert "unique-marker-from-a" in client.calls[0]
        assert "unique-marker-from-b" in client.calls[0]
        row = await _get_overview_row(session, notebook.id)
        assert row.status == OverviewStatus.READY

    async def test_excludes_chunks_from_documents_that_are_not_ready(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.flush()
        ready_doc = Document(
            notebook_id=notebook.id,
            filename="ready.pdf",
            file_path="/tmp/ready.pdf",
            status=DocumentStatus.READY,
        )
        processing_doc = Document(
            notebook_id=notebook.id,
            filename="processing.pdf",
            file_path="/tmp/processing.pdf",
            status=DocumentStatus.PROCESSING,
        )
        session.add_all([ready_doc, processing_doc])
        await session.commit()
        await session.refresh(ready_doc)
        await session.refresh(processing_doc)
        session.add(Chunk(document_id=ready_doc.id, chunk_index=0, text="ready-content", page_number=1))
        session.add(
            Chunk(document_id=processing_doc.id, chunk_index=0, text="not-yet-ready-content", page_number=1)
        )
        await session.commit()

        response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient([response])

        await generate_overview(notebook.id, session, client)

        assert "ready-content" in client.calls[0]
        assert "not-yet-ready-content" not in client.calls[0]

    async def test_multi_section_document_calls_map_then_reduce(self, session: AsyncSession) -> None:
        chunks = ["word " * 200 for _ in range(40)]  # forces multiple sections
        notebook = await _create_notebook_with_ready_document(session, chunks)
        section_response = json.dumps({"summary": "A section summary."})
        final_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": ["c"]}], "estimated_minutes": 20}
        )
        num_sections = len(_build_sections([_chunk(c, i) for i, c in enumerate(chunks)]))
        client = ScriptedClient([section_response] * num_sections + [final_response])

        await generate_overview(notebook.id, session, client)

        row = await _get_overview_row(session, notebook.id)
        assert row.status == OverviewStatus.READY
        # one map call per section, plus exactly one reduce/synthesis call
        assert len(client.calls) == num_sections + 1

    async def test_ollama_unreachable_fails_with_specific_reason(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id

        await generate_overview(notebook_id, session, UnreachableClient())

        row = await _get_overview_row(session, notebook_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "ollama_unreachable"

    async def test_malformed_json_retries_then_fails_with_specific_reason(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient(["not valid json", "{\"still\": \"wrong shape\"}"])

        await generate_overview(notebook_id, session, client)

        row = await _get_overview_row(session, notebook_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "invalid_llm_response"
        assert len(client.calls) == 2  # retried exactly once before giving up

    async def test_recovers_after_a_transient_malformed_response(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        good_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient(["not valid json", good_response])

        await generate_overview(notebook.id, session, client)

        row = await _get_overview_row(session, notebook.id)
        assert row.status == OverviewStatus.READY

    async def test_notebook_with_no_ready_documents_fails_with_no_content_reason(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.commit()
        await session.refresh(notebook)
        notebook_id = notebook.id

        await generate_overview(notebook_id, session, ScriptedClient([]))

        row = await _get_overview_row(session, notebook_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "no_content"

    async def test_never_touches_document_status(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        result = await session.execute(select(Document).where(Document.notebook_id == notebook.id))
        doc = result.scalar_one()
        original_status = doc.status

        await generate_overview(notebook.id, session, UnreachableClient())

        await session.refresh(doc)
        assert doc.status == original_status

    async def test_missing_notebook_id_is_a_noop(self, session: AsyncSession) -> None:
        await generate_overview("does-not-exist", session, UnreachableClient())  # must not raise

    async def test_notebook_deleted_during_llm_call_does_not_mark_overview_ready(
        self, session: AsyncSession
    ) -> None:
        """Simulates a concurrent notebook DELETE landing while the (possibly
        slow, multi-call) LLM work is in flight — mirrors the analogous guard
        in 6.1's processing_pipeline.py for the same class of race."""
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        good_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )

        class DeletingClient:
            async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
                nb = await session.get(Notebook, notebook_id)
                if nb is not None:
                    await session.delete(nb)
                    await session.commit()
                return good_response

        await generate_overview(notebook_id, session, DeletingClient())

        assert await session.get(Notebook, notebook_id) is None
        row = await _get_overview_row(session, notebook_id)
        # Generation was in flight when the notebook vanished — the result
        # must not be persisted as READY for a notebook that no longer exists.
        assert row is None or row.status != OverviewStatus.READY

    async def test_unexpected_exception_never_propagates_and_document_status_is_preserved(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The critical regression test: any bug anywhere in overview
        generation — even a completely unanticipated one, like the
        IntegrityError race this was written to catch — must never propagate
        out of generate_overview. It's called from inside process_document's
        own try/except, and an escaped exception there would incorrectly
        revert a successfully-processed Document back to FAILED and delete
        its embeddings, which is exactly the bug this guards against."""
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        result = await session.execute(select(Document).where(Document.notebook_id == notebook.id))
        doc = result.scalar_one()
        original_status = doc.status

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated bug in overview bookkeeping")

        monkeypatch.setattr("app.services.overview_generation._get_or_create_overview", _boom)

        await generate_overview(notebook.id, session, UnreachableClient())  # must not raise

        await session.refresh(doc)
        assert doc.status == original_status

    async def test_concurrent_calls_for_the_same_notebook_are_serialized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for a real race: two documents in the same
        notebook finishing processing close together each trigger their own
        generate_overview call with an independent session, mirroring how
        background tasks actually run in production. Without serialization,
        both could read/synthesize/write concurrently and whichever commits
        last would silently win even if it saw fewer ready documents.

        This isolates just the locking contract — the actual generation body
        is replaced with a stand-in that tracks how many copies of itself are
        running at once — rather than depending on real DB/LLM timing, which
        proved flaky (real I/O happened to serialize things by luck even
        without the lock, so it passed either way)."""
        concurrent_count = 0
        max_concurrent = 0

        async def fake_body(notebook_id: str, session, client) -> None:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.02)
            concurrent_count -= 1

        monkeypatch.setattr(
            "app.services.overview_generation._generate_overview_body", fake_body
        )

        async def run() -> None:
            await generate_overview("shared-notebook-id", None, UnreachableClient())  # type: ignore[arg-type]

        await asyncio.gather(run(), run(), run())

        assert max_concurrent == 1, "overview generation for the same notebook must not overlap"


class TestAutoTitling:
    async def test_renames_a_default_named_notebook_from_the_overview_content(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some content about machine learning."], notebook_name="Untitled"
        )
        synthesis_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "Gradient Descent", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        title_response = json.dumps({"title": "Machine Learning Basics"})
        client = ScriptedClient([synthesis_response, title_response])

        await generate_overview(notebook.id, session, client)

        await session.refresh(notebook)
        assert notebook.name == "Machine Learning Basics"

    async def test_renames_a_numbered_untitled_notebook(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some content."], notebook_name="Untitled 2"
        )
        synthesis_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        title_response = json.dumps({"title": "Organic Chemistry"})
        client = ScriptedClient([synthesis_response, title_response])

        await generate_overview(notebook.id, session, client)

        await session.refresh(notebook)
        assert notebook.name == "Organic Chemistry"

    async def test_does_not_rename_a_notebook_the_user_already_renamed(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some content."], notebook_name="Learning Python"
        )
        synthesis_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        # Only one response queued — if the client is asked for a title, the
        # test fails with an IndexError, proving auto-titling was skipped.
        client = ScriptedClient([synthesis_response])

        await generate_overview(notebook.id, session, client)

        await session.refresh(notebook)
        assert notebook.name == "Learning Python"
        assert len(client.calls) == 1

    async def test_autotitle_failure_does_not_fail_the_overview(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some content."], notebook_name="Untitled"
        )
        synthesis_response = json.dumps(
            {"short_summary": "s", "topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient([synthesis_response, "not valid json"])

        await generate_overview(notebook.id, session, client)

        row = await _get_overview_row(session, notebook.id)
        assert row.status == OverviewStatus.READY
        await session.refresh(notebook)
        assert notebook.name == "Untitled"

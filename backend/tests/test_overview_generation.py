import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, Notebook, Overview, OverviewStatus
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


async def _create_document_with_chunks(session: AsyncSession, chunk_texts: list[str]) -> Document:
    notebook = Notebook(name="Test Notebook")
    session.add(notebook)
    await session.flush()
    doc = Document(notebook_id=notebook.id, filename="notes.pdf", file_path="/tmp/notes.pdf")
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    for i, text in enumerate(chunk_texts):
        session.add(Chunk(document_id=doc.id, chunk_index=i, text=text, page_number=1))
    await session.commit()
    return doc


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


async def _get_overview_row(session: AsyncSession, document_id: str) -> Overview | None:
    result = await session.execute(select(Overview).where(Overview.document_id == document_id))
    return result.scalar_one_or_none()


class TestGenerateOverview:
    async def test_success_produces_ready_overview_with_topics(self, session: AsyncSession) -> None:
        doc = await _create_document_with_chunks(session, ["Some study content about biology."])
        document_id = doc.id
        response = json.dumps(
            {
                "topics": [
                    {"title": "Cell Biology", "summary": "Covers cell structure.", "key_concepts": ["nucleus"]}
                ],
                "estimated_minutes": 15,
            }
        )
        client = ScriptedClient([response])

        await generate_overview(document_id, session, client)

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.READY
        assert row.estimated_minutes == 15
        topics = json.loads(row.topics_json)
        assert topics[0]["title"] == "Cell Biology"

    async def test_multi_section_document_calls_map_then_reduce(self, session: AsyncSession) -> None:
        chunks = ["word " * 200 for _ in range(40)]  # forces multiple sections
        doc = await _create_document_with_chunks(session, chunks)
        document_id = doc.id
        section_response = json.dumps({"summary": "A section summary."})
        final_response = json.dumps(
            {"topics": [{"title": "T", "summary": "s", "key_concepts": ["c"]}], "estimated_minutes": 20}
        )
        num_sections = len(_build_sections([_chunk(c, i) for i, c in enumerate(chunks)]))
        client = ScriptedClient([section_response] * num_sections + [final_response])

        await generate_overview(document_id, session, client)

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.READY
        # one map call per section, plus exactly one reduce/synthesis call
        assert len(client.calls) == num_sections + 1

    async def test_ollama_unreachable_fails_with_specific_reason(self, session: AsyncSession) -> None:
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id

        await generate_overview(document_id, session, UnreachableClient())

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "ollama_unreachable"

    async def test_malformed_json_retries_then_fails_with_specific_reason(
        self, session: AsyncSession
    ) -> None:
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id
        client = ScriptedClient(["not valid json", "{\"still\": \"wrong shape\"}"])

        await generate_overview(document_id, session, client)

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "invalid_llm_response"
        assert len(client.calls) == 2  # retried exactly once before giving up

    async def test_recovers_after_a_transient_malformed_response(self, session: AsyncSession) -> None:
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id
        good_response = json.dumps(
            {"topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )
        client = ScriptedClient(["not valid json", good_response])

        await generate_overview(document_id, session, client)

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.READY

    async def test_document_with_no_chunks_fails_with_no_content_reason(
        self, session: AsyncSession
    ) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.flush()
        doc = Document(notebook_id=notebook.id, filename="empty.pdf", file_path="/tmp/empty.pdf")
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        document_id = doc.id

        await generate_overview(document_id, session, ScriptedClient([]))

        row = await _get_overview_row(session, document_id)
        assert row.status == OverviewStatus.FAILED
        assert row.error_reason == "no_content"

    async def test_never_touches_document_status(self, session: AsyncSession) -> None:
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id
        original_status = doc.status

        await generate_overview(document_id, session, UnreachableClient())

        await session.refresh(doc)
        assert doc.status == original_status

    async def test_missing_document_id_is_a_noop(self, session: AsyncSession) -> None:
        await generate_overview("does-not-exist", session, UnreachableClient())  # must not raise

    async def test_document_deleted_during_llm_call_does_not_mark_overview_ready(
        self, session: AsyncSession
    ) -> None:
        """Simulates a concurrent DELETE landing while the (possibly slow,
        multi-call) LLM work is in flight — mirrors the analogous guard in
        6.1's processing_pipeline.py for the same class of race."""
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id
        good_response = json.dumps(
            {"topics": [{"title": "T", "summary": "s", "key_concepts": []}], "estimated_minutes": 10}
        )

        class DeletingClient:
            async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
                document = await session.get(Document, document_id)
                if document is not None:
                    await session.delete(document)
                    await session.commit()
                return good_response

        await generate_overview(document_id, session, DeletingClient())

        assert await session.get(Document, document_id) is None
        row = await _get_overview_row(session, document_id)
        # Generation was in flight when the document vanished — the result
        # must not be persisted as READY for a document that no longer exists.
        assert row.status != OverviewStatus.READY

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
        doc = await _create_document_with_chunks(session, ["Some content."])
        document_id = doc.id
        original_status = doc.status

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated bug in overview bookkeeping")

        monkeypatch.setattr("app.services.overview_generation._get_or_create_overview", _boom)

        await generate_overview(document_id, session, UnreachableClient())  # must not raise

        await session.refresh(doc)
        assert doc.status == original_status

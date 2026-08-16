from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, DocumentStatus
from app.services.processing_pipeline import process_document, reconcile_interrupted_documents
from app.services.vector_store import VectorStore

FIXTURES = Path(__file__).parent / "fixtures"


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
    return VectorStore(persist_dir=tmp_path / "chroma", collection_name="pipeline_test")


async def _create_document(session: AsyncSession, fixture_name: str) -> Document:
    doc = Document(filename=fixture_name, file_path=str(FIXTURES / fixture_name))
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def test_normal_pdf_processes_to_ready(session: AsyncSession, vector_store: VectorStore) -> None:
    doc = await _create_document(session, "normal.pdf")

    await process_document(doc.id, session, vector_store)

    await session.refresh(doc)
    assert doc.status == DocumentStatus.READY
    assert doc.chunk_count is not None and doc.chunk_count > 0
    assert doc.page_count == 3

    result = await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
    sql_chunks = result.scalars().all()
    assert len(sql_chunks) == doc.chunk_count
    assert vector_store.count_for_document(doc.id) == doc.chunk_count

    # Retrieval-quality check, not just "no exception raised": a paraphrased query
    # about content actually in the fixture must retrieve the relevant chunk.
    hits = vector_store.query("How are neural networks trained?", top_k=1, document_id=doc.id)
    assert len(hits) == 1
    assert "backpropagation" in hits[0].text.lower()


@pytest.mark.parametrize(
    ("fixture_name", "expected_reason"),
    [
        ("empty.pdf", "empty_document"),
        ("blank_page.pdf", "no_extractable_text"),
        ("corrupted.pdf", "invalid_pdf"),
        ("password.pdf", "password_protected"),
        ("scanned.pdf", "scanned_or_image_only"),
        ("not_a_pdf.pdf", "invalid_pdf"),
    ],
)
async def test_bad_fixtures_process_to_failed_with_correct_reason(
    session: AsyncSession, vector_store: VectorStore, fixture_name: str, expected_reason: str
) -> None:
    doc = await _create_document(session, fixture_name)

    await process_document(doc.id, session, vector_store)

    await session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_reason == expected_reason
    assert vector_store.count_for_document(doc.id) == 0

    result = await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
    assert result.scalars().all() == []


async def test_unexpected_exception_during_embedding_still_resolves_to_failed(
    session: AsyncSession, vector_store: VectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr("app.services.processing_pipeline.embed_texts", _boom)

    doc = await _create_document(session, "normal.pdf")

    await process_document(doc.id, session, vector_store)

    await session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_reason == "processing_error"
    assert "embedding backend unavailable" in (doc.error_detail or "")
    assert vector_store.count_for_document(doc.id) == 0


async def test_missing_document_id_is_a_noop(session: AsyncSession, vector_store: VectorStore) -> None:
    await process_document("does-not-exist", session, vector_store)  # must not raise


async def test_reconcile_interrupted_documents_marks_stuck_docs_failed(
    session: AsyncSession,
) -> None:
    doc = await _create_document(session, "normal.pdf")
    doc.status = DocumentStatus.PROCESSING
    await session.commit()

    reconciled_count = await reconcile_interrupted_documents(session)

    await session.refresh(doc)
    assert reconciled_count == 1
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_reason == "interrupted"


async def test_reconcile_interrupted_documents_leaves_settled_docs_alone(
    session: AsyncSession,
) -> None:
    doc = await _create_document(session, "normal.pdf")
    doc.status = DocumentStatus.READY
    await session.commit()

    reconciled_count = await reconcile_interrupted_documents(session)

    await session.refresh(doc)
    assert reconciled_count == 0
    assert doc.status == DocumentStatus.READY


async def test_document_deleted_before_vector_write_leaves_no_orphaned_vectors(
    session: AsyncSession, vector_store: VectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates DELETE /documents/{id} racing with an in-flight background
    processing run: the document vanishes between embedding and the vector
    write. process_document must not write vectors for a document that no
    longer exists anywhere else."""
    doc = await _create_document(session, "normal.pdf")

    async def _always_gone(_session: AsyncSession, _document_id: str) -> bool:
        return False

    monkeypatch.setattr("app.services.processing_pipeline._document_still_exists", _always_gone)

    await process_document(doc.id, session, vector_store)

    assert vector_store.count_for_document(doc.id) == 0


async def test_document_deleted_after_vector_write_cleans_up_orphaned_vectors(
    session: AsyncSession, vector_store: VectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same race, but the delete lands in the narrower window after vectors
    were already written — the pipeline must clean those up rather than
    leaving them orphaned."""
    doc = await _create_document(session, "normal.pdf")
    calls = {"count": 0}

    async def _gone_on_second_check(_session: AsyncSession, _document_id: str) -> bool:
        calls["count"] += 1
        return calls["count"] == 1  # exists on the pre-write check, gone after

    monkeypatch.setattr(
        "app.services.processing_pipeline._document_still_exists", _gone_on_second_check
    )

    await process_document(doc.id, session, vector_store)

    assert vector_store.count_for_document(doc.id) == 0

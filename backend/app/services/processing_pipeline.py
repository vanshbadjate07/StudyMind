import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import UnsupportedDocumentError
from app.models import Chunk, Document, DocumentStatus
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.extraction import ExtractedDocument, extract_text
from app.services.vector_store import VectorStore, get_vector_store


async def process_document(
    document_id: str,
    session: AsyncSession,
    vector_store: VectorStore | None = None,
) -> None:
    """Runs extract -> chunk -> embed -> store for one document, updating its
    status at every stage. Always resolves to READY or FAILED — never leaves a
    document stuck in PROCESSING, regardless of where a failure occurs."""
    vector_store = vector_store or get_vector_store()

    document = await session.get(Document, document_id)
    if document is None:
        return

    document.status = DocumentStatus.PROCESSING
    await session.commit()

    try:
        # PyMuPDF and sentence-transformers are sync/CPU-bound; thread-offload
        # so a large document doesn't block the event loop for every other
        # request (health checks, other uploads, status polling) while it runs.
        extracted = await asyncio.to_thread(extract_text, Path(document.file_path))
        chunks, chunk_texts = _build_chunks(document_id, extracted)
        if not chunks:
            raise UnsupportedDocumentError("no_extractable_text")

        embeddings = await asyncio.to_thread(embed_texts, chunk_texts)

        if not await _document_still_exists(session, document_id):
            return  # deleted while extraction/embedding was running

        vector_store.add(
            document_id=document_id,
            chunk_ids=[c.id for c in chunks],
            texts=chunk_texts,
            embeddings=embeddings,
            page_numbers=[c.page_number for c in chunks],
        )

        if not await _document_still_exists(session, document_id):
            # Deleted in the brief window around the vector write above —
            # clean up what was just written so nothing is orphaned.
            vector_store.delete_document(document_id)
            return

        await _mark_ready(session, document_id, chunks, extracted)
    except UnsupportedDocumentError as exc:
        vector_store.delete_document(document_id)
        await _mark_failed(session, document_id, exc.reason, exc.detail)
    except Exception as exc:  # any unexpected failure must still resolve to FAILED
        vector_store.delete_document(document_id)
        await _mark_failed(session, document_id, "processing_error", str(exc))


async def _document_still_exists(session: AsyncSession, document_id: str) -> bool:
    return await session.get(Document, document_id) is not None


async def reconcile_interrupted_documents(session: AsyncSession) -> int:
    """Marks any document left in PENDING/PROCESSING as FAILED on startup.
    BackgroundTasks are in-process and not durable — if the server crashed or
    restarted mid-processing, no code path would otherwise ever pick that
    document back up, leaving it stuck forever. Returns how many were reconciled."""
    result = await session.execute(
        select(Document).where(
            Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING])
        )
    )
    interrupted = list(result.scalars().all())
    for document in interrupted:
        document.status = DocumentStatus.FAILED
        document.error_reason = "interrupted"
        document.error_detail = "Processing was interrupted by a server restart."
    if interrupted:
        await session.commit()
    return len(interrupted)


def _build_chunks(
    document_id: str, extracted: ExtractedDocument
) -> tuple[list[Chunk], list[str]]:
    chunks: list[Chunk] = []
    texts: list[str] = []
    for page in extracted.pages:
        for piece in chunk_text(page.text, page_number=page.page_number):
            chunks.append(
                Chunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_index=len(chunks),
                    text=piece.text,
                    page_number=piece.page_number,
                )
            )
            texts.append(piece.text)
    return chunks, texts


async def _mark_ready(
    session: AsyncSession, document_id: str, chunks: list[Chunk], extracted: ExtractedDocument
) -> None:
    document = await session.get(Document, document_id)
    if document is None:
        return
    session.add_all(chunks)
    document.status = DocumentStatus.READY
    document.page_count = extracted.page_count
    document.char_count = extracted.char_count
    document.chunk_count = len(chunks)
    document.error_reason = None
    document.error_detail = None
    await session.commit()


async def _mark_failed(session: AsyncSession, document_id: str, reason: str, detail: str) -> None:
    await session.rollback()
    document = await session.get(Document, document_id)
    if document is None:
        return
    document.status = DocumentStatus.FAILED
    document.error_reason = reason
    document.error_detail = detail or None
    await session.commit()

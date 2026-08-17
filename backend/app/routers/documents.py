import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.db import get_session
from app.models import Chunk, Document
from app.schemas import DocumentRead
from app.services.overview_generation import maybe_regenerate_notebook_overview
from app.services.vector_store import get_vector_store

router = APIRouter(prefix="/documents", tags=["documents"])


async def cleanup_document_storage(document: Document) -> None:
    """Removes the on-disk file and vector-store entries for a document.
    Doesn't touch the database — callers handle DB row deletion (and commit)
    themselves, since single-document delete and notebook cascade-delete want
    different transaction shapes."""
    shutil.rmtree(Path(document.file_path).parent, ignore_errors=True)
    get_vector_store().delete_document(document.id)


async def _run_overview_regeneration(notebook_id: str) -> None:
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` are respected here —
    # see app/main.py's lifespan for the full explanation of this pattern.
    async with db.async_session_factory() as session:
        await maybe_regenerate_notebook_overview(notebook_id, session)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: str, session: AsyncSession = Depends(get_session)) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> None:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    notebook_id = document.notebook_id

    await cleanup_document_storage(document)

    await session.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
    await session.delete(document)
    await session.commit()

    # The notebook's combined overview no longer reflects this document's
    # content — regenerate it (or drop it if no ready documents remain).
    background_tasks.add_task(_run_overview_regeneration, notebook_id)

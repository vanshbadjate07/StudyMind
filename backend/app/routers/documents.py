import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.db import get_session
from app.models import Chunk, Document, DocumentStatus, Overview, OverviewStatus
from app.schemas import DocumentRead, OverviewRead
from app.services.overview_generation import generate_overview
from app.services.vector_store import get_vector_store

router = APIRouter(prefix="/documents", tags=["documents"])


async def cleanup_document_storage(document: Document) -> None:
    """Removes the on-disk file and vector-store entries for a document.
    Doesn't touch the database — callers handle DB row deletion (and commit)
    themselves, since single-document delete and notebook cascade-delete want
    different transaction shapes."""
    shutil.rmtree(Path(document.file_path).parent, ignore_errors=True)
    get_vector_store().delete_document(document.id)


async def _run_overview_generation(document_id: str) -> None:
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` are respected here —
    # see app/main.py's lifespan for the full explanation of this pattern.
    async with db.async_session_factory() as session:
        await generate_overview(document_id, session)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: str, session: AsyncSession = Depends(get_session)) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, session: AsyncSession = Depends(get_session)) -> None:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    await cleanup_document_storage(document)

    await session.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
    await session.execute(sa_delete(Overview).where(Overview.document_id == document_id))
    await session.delete(document)
    await session.commit()


@router.get("/{document_id}/overview", response_model=OverviewRead)
async def get_overview(document_id: str, session: AsyncSession = Depends(get_session)) -> OverviewRead:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    result = await session.execute(select(Overview).where(Overview.document_id == document_id))
    overview = result.scalar_one_or_none()
    if overview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Overview has not started yet."
        )
    return OverviewRead.from_model(overview)


@router.post(
    "/{document_id}/overview/regenerate", response_model=OverviewRead, status_code=status.HTTP_202_ACCEPTED
)
async def regenerate_overview(
    document_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> OverviewRead:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is not ready yet (status: {document.status.value}).",
        )

    result = await session.execute(select(Overview).where(Overview.document_id == document_id))
    overview = result.scalar_one_or_none()
    if overview is None:
        overview = Overview(document_id=document_id, status=OverviewStatus.PENDING)
        session.add(overview)
    elif overview.status == OverviewStatus.GENERATING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Overview generation is already in progress for this document.",
        )
    else:
        overview.status = OverviewStatus.PENDING
        overview.error_reason = None
        overview.error_detail = None
    await session.commit()
    await session.refresh(overview)

    background_tasks.add_task(_run_overview_generation, document_id)

    return OverviewRead.from_model(overview)

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.config import settings
from app.db import get_session
from app.models import Chunk, Document, DocumentStatus, Notebook, Overview, OverviewStatus
from app.routers.documents import cleanup_document_storage
from app.schemas import (
    DocumentList,
    DocumentRead,
    GoalUpdate,
    NotebookCreate,
    NotebookList,
    NotebookRead,
    NotebookUpdate,
    OverviewRead,
)
from app.services.overview_generation import generate_overview
from app.services.processing_pipeline import process_document

router = APIRouter(prefix="/notebooks", tags=["notebooks"])

PDF_MAGIC_BYTES = b"%PDF-"
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_DISPLAY_FILENAME_LENGTH = 255
STORED_FILENAME = "source.pdf"


@router.post("", response_model=NotebookRead, status_code=status.HTTP_201_CREATED)
async def create_notebook(
    body: NotebookCreate, session: AsyncSession = Depends(get_session)
) -> Notebook:
    notebook = Notebook(name=(body.name or "").strip() or "Untitled")
    session.add(notebook)
    await session.commit()
    await session.refresh(notebook)
    return notebook


@router.get("", response_model=NotebookList)
async def list_notebooks(session: AsyncSession = Depends(get_session)) -> NotebookList:
    result = await session.execute(select(Notebook).order_by(Notebook.created_at.desc()))
    return NotebookList(notebooks=list(result.scalars().all()))


@router.get("/{notebook_id}", response_model=NotebookRead)
async def get_notebook(notebook_id: str, session: AsyncSession = Depends(get_session)) -> Notebook:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")
    return notebook


@router.patch("/{notebook_id}", response_model=NotebookRead)
async def update_notebook(
    notebook_id: str, body: NotebookUpdate, session: AsyncSession = Depends(get_session)
) -> Notebook:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")
    notebook.name = body.name.strip() or notebook.name
    await session.commit()
    await session.refresh(notebook)
    return notebook


@router.post("/{notebook_id}/goal", response_model=NotebookRead)
async def set_notebook_goal(
    notebook_id: str, body: GoalUpdate, session: AsyncSession = Depends(get_session)
) -> Notebook:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")
    notebook.goal_type = body.goal_type
    notebook.goal_description = (body.goal_description or "").strip() or None
    await session.commit()
    await session.refresh(notebook)
    return notebook


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook(notebook_id: str, session: AsyncSession = Depends(get_session)) -> None:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(select(Document).where(Document.notebook_id == notebook_id))
    documents = list(result.scalars().all())
    for document in documents:
        await cleanup_document_storage(document)
        await session.execute(sa_delete(Chunk).where(Chunk.document_id == document.id))

    await session.execute(sa_delete(Document).where(Document.notebook_id == notebook_id))
    await session.execute(sa_delete(Overview).where(Overview.notebook_id == notebook_id))
    await session.delete(notebook)
    await session.commit()


def _sanitize_display_filename(filename: str | None) -> str:
    """Never used to build a filesystem path — only stored/displayed. The
    on-disk name is always the fixed STORED_FILENAME, so this can't be used
    for path traversal; `Path(...).name` here is purely to avoid showing a
    confusing raw path (e.g. "../../evil.pdf") in the UI."""
    raw = Path(filename or "").name
    cleaned = "".join(ch for ch in raw.strip() if ch.isprintable())
    return cleaned[:MAX_DISPLAY_FILENAME_LENGTH] or "document.pdf"


@router.post("/{notebook_id}/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> Document:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    extension = Path(file.filename or "").suffix.lower()
    if extension not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{extension or 'unknown'}'. Only PDF files are supported.",
        )

    document_id = str(uuid.uuid4())
    document_dir = settings.uploads_dir / document_id
    document_dir.mkdir(parents=True, exist_ok=True)
    # Fixed filename — never derived from user input, so the client-supplied
    # `file.filename` can never influence the on-disk path (no traversal risk).
    dest_path = document_dir / STORED_FILENAME

    try:
        await _save_upload_streaming(file, dest_path)
    except HTTPException:
        shutil.rmtree(document_dir, ignore_errors=True)
        raise

    document = Document(
        id=document_id,
        notebook_id=notebook_id,
        filename=_sanitize_display_filename(file.filename),
        file_path=str(dest_path),
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    background_tasks.add_task(_run_processing, document.id)

    return document


async def _save_upload_streaming(file: UploadFile, dest_path: Path) -> None:
    """Streams the upload to disk in fixed-size chunks so we never hold a huge
    file fully in memory, checking the PDF magic bytes on the first chunk and
    the size limit as we go — both rejections happen before the file is fully
    written."""
    total_bytes = 0
    first_chunk = True
    with dest_path.open("wb") as out:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            if first_chunk:
                if not chunk.startswith(PDF_MAGIC_BYTES):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="File does not look like a valid PDF.",
                    )
                first_chunk = False
            total_bytes += len(chunk)
            if total_bytes > settings.max_upload_bytes:
                limit_mb = settings.max_upload_bytes // (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {limit_mb}MB upload limit.",
                )
            out.write(chunk)

    if total_bytes == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")


async def _run_processing(document_id: str) -> None:
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` are respected here —
    # see app/main.py's lifespan for the full explanation of this pattern.
    async with db.async_session_factory() as session:
        await process_document(document_id, session)


@router.get("/{notebook_id}/documents", response_model=DocumentList)
async def list_notebook_documents(
    notebook_id: str, session: AsyncSession = Depends(get_session)
) -> DocumentList:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(
        select(Document).where(Document.notebook_id == notebook_id).order_by(Document.created_at.desc())
    )
    return DocumentList(documents=list(result.scalars().all()))


async def _run_overview_generation(notebook_id: str) -> None:
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` are respected here —
    # see app/main.py's lifespan for the full explanation of this pattern.
    async with db.async_session_factory() as session:
        await generate_overview(notebook_id, session)


@router.get("/{notebook_id}/overview", response_model=OverviewRead)
async def get_overview(notebook_id: str, session: AsyncSession = Depends(get_session)) -> OverviewRead:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(select(Overview).where(Overview.notebook_id == notebook_id))
    overview = result.scalar_one_or_none()
    if overview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Overview has not started yet."
        )
    return OverviewRead.from_model(overview)


@router.post(
    "/{notebook_id}/overview/regenerate", response_model=OverviewRead, status_code=status.HTTP_202_ACCEPTED
)
async def regenerate_overview(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> OverviewRead:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    has_ready = await session.execute(
        select(Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .limit(1)
    )
    if has_ready.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No ready documents in this notebook yet.",
        )

    result = await session.execute(select(Overview).where(Overview.notebook_id == notebook_id))
    overview = result.scalar_one_or_none()
    if overview is None:
        overview = Overview(notebook_id=notebook_id, status=OverviewStatus.PENDING)
        session.add(overview)
    elif overview.status == OverviewStatus.GENERATING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Overview generation is already in progress for this notebook.",
        )
    else:
        overview.status = OverviewStatus.PENDING
        overview.error_reason = None
        overview.error_detail = None
    await session.commit()
    await session.refresh(overview)

    background_tasks.add_task(_run_overview_generation, notebook_id)

    return OverviewRead.from_model(overview)

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory, get_session
from app.models import Chunk, Document, DocumentStatus
from app.schemas import DocumentList, DocumentRead
from app.services.processing_pipeline import process_document
from app.services.vector_store import get_vector_store

router = APIRouter(prefix="/documents", tags=["documents"])

PDF_MAGIC_BYTES = b"%PDF-"
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_DISPLAY_FILENAME_LENGTH = 255
STORED_FILENAME = "source.pdf"


def _sanitize_display_filename(filename: str | None) -> str:
    """Never used to build a filesystem path — only stored/displayed. The
    on-disk name is always the fixed STORED_FILENAME, so this can't be used
    for path traversal; `Path(...).name` here is purely to avoid showing a
    confusing raw path (e.g. "../../evil.pdf") in the UI."""
    raw = Path(filename or "").name
    cleaned = "".join(ch for ch in raw.strip() if ch.isprintable())
    return cleaned[:MAX_DISPLAY_FILENAME_LENGTH] or "document.pdf"


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> Document:
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
    async with async_session_factory() as session:
        await process_document(document_id, session)


@router.get("", response_model=DocumentList)
async def list_documents(session: AsyncSession = Depends(get_session)) -> DocumentList:
    result = await session.execute(select(Document).order_by(Document.created_at.desc()))
    return DocumentList(documents=list(result.scalars().all()))


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

    shutil.rmtree(Path(document.file_path).parent, ignore_errors=True)
    get_vector_store().delete_document(document_id)

    await session.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
    await session.delete(document)
    await session.commit()

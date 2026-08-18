from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.db import get_session
from app.models import Document, DocumentStatus, Notebook, Presentation, PresentationStatus
from app.schemas import PresentationGenerateRequest, PresentationRead
from app.services.presentation_generation import generate_presentation

router = APIRouter(prefix="/notebooks/{notebook_id}/presentation", tags=["presentation"])


async def _run_presentation_generation(notebook_id: str, options: PresentationGenerateRequest) -> None:
    # Accessed via the `db` module (not a direct `from app.db import
    # async_session_factory`) so tests that monkeypatch `db.async_session_factory`
    # are respected here — see app/main.py's lifespan for the full explanation.
    async with db.async_session_factory() as session:
        await generate_presentation(notebook_id, session, options=options)


@router.get("", response_model=PresentationRead)
async def get_presentation(notebook_id: str, session: AsyncSession = Depends(get_session)) -> PresentationRead:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
    presentation = result.scalar_one_or_none()
    if presentation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No presentation has been generated yet.")
    return PresentationRead.from_model(presentation)


@router.post("/generate", response_model=PresentationRead, status_code=status.HTTP_202_ACCEPTED)
async def generate_notebook_presentation(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    body: PresentationGenerateRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> PresentationRead:
    options = body or PresentationGenerateRequest()
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

    result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
    presentation = result.scalar_one_or_none()
    if presentation is None:
        presentation = Presentation(notebook_id=notebook_id, status=PresentationStatus.PENDING)
        session.add(presentation)
    elif presentation.status == PresentationStatus.GENERATING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Presentation generation is already in progress for this notebook.",
        )
    else:
        presentation.status = PresentationStatus.PENDING
        presentation.error_reason = None
        presentation.error_detail = None
    await session.commit()
    await session.refresh(presentation)

    background_tasks.add_task(_run_presentation_generation, notebook_id, options)

    return PresentationRead.from_model(presentation)


@router.get("/download")
async def download_notebook_presentation(
    notebook_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
    presentation = result.scalar_one_or_none()
    if presentation is None or presentation.status != PresentationStatus.READY or not presentation.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ready presentation to download.")

    file_path = Path(presentation.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Presentation file is missing.")

    safe_name = "".join(c for c in notebook.name if c.isalnum() or c in " -_").strip() or "presentation"
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{safe_name}.pptx",
    )

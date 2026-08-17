from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.db import get_session
from app.models import Document, DocumentStatus, Notebook, Quiz, QuizStatus
from app.schemas import QuizRead
from app.services.quiz_generation import generate_quiz

router = APIRouter(prefix="/notebooks/{notebook_id}/quiz", tags=["quiz"])


async def _run_quiz_generation(notebook_id: str) -> None:
    # Accessed via the `db` module (not `from app.db import async_session_factory`)
    # so tests that monkeypatch `db.async_session_factory` are respected here —
    # see app/main.py's lifespan for the full explanation of this pattern.
    async with db.async_session_factory() as session:
        await generate_quiz(notebook_id, session)


@router.get("", response_model=QuizRead)
async def get_quiz(notebook_id: str, session: AsyncSession = Depends(get_session)) -> QuizRead:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")

    result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
    quiz = result.scalar_one_or_none()
    if quiz is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No quiz has been generated yet.")
    return QuizRead.from_model(quiz)


@router.post("/generate", response_model=QuizRead, status_code=status.HTTP_202_ACCEPTED)
async def generate_notebook_quiz(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> QuizRead:
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

    result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
    quiz = result.scalar_one_or_none()
    if quiz is None:
        quiz = Quiz(notebook_id=notebook_id, status=QuizStatus.PENDING)
        session.add(quiz)
    elif quiz.status == QuizStatus.GENERATING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quiz generation is already in progress for this notebook.",
        )
    else:
        quiz.status = QuizStatus.PENDING
        quiz.error_reason = None
        quiz.error_detail = None
    await session.commit()
    await session.refresh(quiz)

    background_tasks.add_task(_run_quiz_generation, notebook_id)

    return QuizRead.from_model(quiz)

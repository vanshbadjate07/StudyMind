"""Mock interview endpoints (PRD 6.7).

Two prefixes rather than one: starting and listing interviews are scoped to a
notebook, but answering and ending act on a session by id, which the client
already holds. Nesting the per-turn routes under the notebook too would make
every answer request carry a notebook id it doesn't need and can't be
trusted on anyway.

These routes are synchronous: each one performs its LLM call inline and
returns the result, rather than the 202-plus-polling shape the generated
artefacts use. See app/services/interview.py for why.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import InterviewError
from app.models import Document, DocumentStatus, InterviewSession, Notebook
from app.schemas import (
    AnswerScoringMetrics,
    InterviewAnswerRequest,
    InterviewSessionRead,
    InterviewStartRequest,
)
from app.services import interview as interview_service
from app.services.answer_scoring import load_metrics
from app.services.llm_errors import LLMTimeoutError, LLMUnreachableError

logger = logging.getLogger(__name__)

notebook_router = APIRouter(prefix="/notebooks/{notebook_id}/interview", tags=["interview"])
session_router = APIRouter(prefix="/interview", tags=["interview"])

# Human-readable messages for the stable reason codes, kept here because
# these endpoints answer synchronously: there's no status row for the
# frontend's errorMessages.ts to translate, so the message travels in the
# HTTP detail instead.
_REASON_MESSAGES = {
    "no_content": "There's no processed material in this notebook to interview on yet.",
    "invalid_llm_response": "The AI service returned something unexpected. Please try again.",
    "no_pending_question": "There's no question waiting to be answered.",
    "interview_completed": "This interview has already finished.",
}


def _raise_for_interview_error(exc: InterviewError) -> None:
    detail = _REASON_MESSAGES.get(exc.reason) or exc.detail or "Something went wrong."
    # 409 for the two "the interview isn't in a state that allows this" cases
    # (the client can recover by re-reading the session), 422 for the rest.
    conflict = exc.reason in {"no_pending_question", "interview_completed"}
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    ) from exc


def _raise_for_llm_error(exc: Exception) -> None:
    if isinstance(exc, LLMTimeoutError):
        detail = "The AI service took too long to respond. Please try again."
    else:
        detail = "Couldn't reach the AI service right now. Please try again shortly."
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc


async def _get_notebook(notebook_id: str, session: AsyncSession) -> Notebook:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found.")
    return notebook


async def _get_interview(interview_id: str, session: AsyncSession) -> InterviewSession:
    interview = await session.get(InterviewSession, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    return interview


async def _require_ready_documents(notebook_id: str, session: AsyncSession) -> None:
    result = await session.execute(
        select(Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No ready documents in this notebook yet.",
        )


@notebook_router.get("", response_model=InterviewSessionRead)
async def get_latest_interview(
    notebook_id: str, session: AsyncSession = Depends(get_session)
) -> InterviewSessionRead:
    """The notebook's most recent interview, in progress or finished. 404
    before the first one, which the frontend reads as "null, not an error" -
    the same convention overview, quiz and presentation already use."""
    await _get_notebook(notebook_id, session)
    interview = await interview_service.latest_session_for_notebook(session, notebook_id)
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No interview has been started yet."
        )
    qa_items = await interview_service.load_qa_items(session, interview.id)
    return InterviewSessionRead.from_model(interview, qa_items)


@notebook_router.post("/start", response_model=InterviewSessionRead, status_code=status.HTTP_201_CREATED)
async def start_interview(
    notebook_id: str,
    body: InterviewStartRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> InterviewSessionRead:
    options = body or InterviewStartRequest()
    notebook = await _get_notebook(notebook_id, session)
    await _require_ready_documents(notebook_id, session)

    existing = await interview_service.in_progress_session_for_notebook(session, notebook_id)
    if existing is not None:
        # Deliberately not auto-ending it: an in-progress interview is work
        # the user did, and silently discarding it to honour a stray click
        # would lose that. The client ends it explicitly or resumes it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An interview is already in progress for this notebook.",
        )

    try:
        interview, qa_items = await interview_service.start_interview(
            notebook, options, session
        )
    except InterviewError as exc:
        _raise_for_interview_error(exc)
    except (LLMUnreachableError, LLMTimeoutError) as exc:
        _raise_for_llm_error(exc)
    return InterviewSessionRead.from_model(interview, qa_items)


@session_router.get("/{interview_id}", response_model=InterviewSessionRead)
async def get_interview(
    interview_id: str, session: AsyncSession = Depends(get_session)
) -> InterviewSessionRead:
    interview = await _get_interview(interview_id, session)
    qa_items = await interview_service.load_qa_items(session, interview.id)
    return InterviewSessionRead.from_model(interview, qa_items)


@session_router.post("/{interview_id}/answer", response_model=InterviewSessionRead)
async def answer_interview_question(
    interview_id: str,
    body: InterviewAnswerRequest,
    session: AsyncSession = Depends(get_session),
) -> InterviewSessionRead:
    """Scores the pending answer and returns the whole session, including the
    next question (or the final report if the interview just finished).

    Returning the full session rather than just the new turn keeps the client
    from having to merge state: one response is the complete truth about where
    the interview now stands.
    """
    interview = await _get_interview(interview_id, session)
    notebook = await _get_notebook(interview.notebook_id, session)
    try:
        interview, qa_items = await interview_service.submit_answer(
            notebook, interview, body.answer, session
        )
    except InterviewError as exc:
        _raise_for_interview_error(exc)
    except (LLMUnreachableError, LLMTimeoutError) as exc:
        # The answer itself is already scored and committed by this point, so
        # the user's work survives. The client re-reads the session and uses
        # /continue to pick the interview back up.
        _raise_for_llm_error(exc)
    return InterviewSessionRead.from_model(interview, qa_items)


@session_router.post("/{interview_id}/continue", response_model=InterviewSessionRead)
async def continue_interview(
    interview_id: str, session: AsyncSession = Depends(get_session)
) -> InterviewSessionRead:
    """Asks the next question for a session that has none pending. The
    recovery path for a question generation that failed after the previous
    answer was already scored."""
    interview = await _get_interview(interview_id, session)
    notebook = await _get_notebook(interview.notebook_id, session)
    try:
        interview, qa_items = await interview_service.continue_interview(
            notebook, interview, session
        )
    except InterviewError as exc:
        _raise_for_interview_error(exc)
    except (LLMUnreachableError, LLMTimeoutError) as exc:
        _raise_for_llm_error(exc)
    return InterviewSessionRead.from_model(interview, qa_items)


@session_router.post("/{interview_id}/end", response_model=InterviewSessionRead)
async def end_interview(
    interview_id: str, session: AsyncSession = Depends(get_session)
) -> InterviewSessionRead:
    """Ends early and builds the report from what was answered so far.
    Idempotent: ending an already-finished interview returns it unchanged
    rather than erroring, so a double click is harmless."""
    interview = await _get_interview(interview_id, session)
    interview, qa_items = await interview_service.end_interview(interview, session)
    return InterviewSessionRead.from_model(interview, qa_items)


@session_router.get("/meta/scoring", response_model=AnswerScoringMetrics)
async def get_scoring_metrics() -> AnswerScoringMetrics:
    """The scoring model's held-out metrics (PRD 6.10), so the UI can state
    how the scorer performs instead of presenting its numbers as self-evident.
    Reports `using_fallback` when no trained artefact is loadable, rather than
    quietly showing metrics for a model that isn't the one doing the scoring."""
    metrics = load_metrics()
    if metrics is None:
        return AnswerScoringMetrics(using_fallback=True)
    return AnswerScoringMetrics(
        held_out_mae=metrics.get("held_out_mae"),
        held_out_r2=metrics.get("held_out_r2"),
        model=metrics.get("model"),
        corpus_size=metrics.get("corpus_size"),
        using_fallback=False,
    )

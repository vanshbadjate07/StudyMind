"""Mock interview (PRD 6.7).

The thing that makes this an agent rather than a quiz is the decision loop in
`decide_next_step`: after every answer the system chooses what to do next
based on how that answer scored, instead of walking a fixed list.

    weak answer                  -> probe the SAME topic with a simpler,
                                    more focused question
    solid answer                 -> advance to a topic not yet covered
    two weak answers in a row
    on one topic                 -> stop probing it, flag it as a weak area,
                                    and move on

That last rule is what keeps "adaptive" from being worse than a fixed list:
without a cap, a topic the user simply doesn't know would absorb every
remaining question.

Scoring is delegated to `answer_scoring` (PRD 6.10) - a trained model over
interpretable features, not the LLM's opinion of its own question. The LLM
writes the question and the ideal answer from the user's material; judging
the user's answer against it is the model's job.

Unlike overview/quiz/presentation, this runs synchronously rather than as a
background task with a polled status row. There's no artefact being built
in the background - the user is waiting for the interviewer's next question,
so a request/response turn is the honest shape.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import InterviewError
from app.models import (
    Chunk,
    Document,
    DocumentStatus,
    InterviewMode,
    InterviewQA,
    InterviewSession,
    InterviewStatus,
    Notebook,
    Overview,
    OverviewStatus,
)
from app.schemas import InterviewQuestionResult, InterviewStartRequest, InterviewTopicsResult
from app.services.answer_scoring import Embedder, score_answer
from app.services.chat import GOAL_PROMPT_HINTS
from app.services.llm_client import LLMClient, get_default_llm_client
from app.services.section_splitting import build_sections
from app.services.vector_store import VectorStore, get_vector_store
from app.models import GoalType

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

QUESTION_PROMPT_TEMPLATE = (
    "You are conducting a mock interview to test how well the candidate "
    "understands their own study material. Ask exactly ONE question."
    "{topic_clause}{probe_clause}{focus_clause}\n\n"
    "{goal_clause}"
    "Base the question strictly on the material below. Do not ask about "
    "anything the material does not cover.\n\n"
    "Respond with ONLY a JSON object matching this exact shape: "
    '{{"question": "the question to ask, one or two sentences", '
    '"ideal_answer": "a complete answer drawn from the material, 2-5 '
    'sentences, written the way a strong candidate would say it out loud", '
    '"key_concepts": ["2 to 6 short noun phrases naming the specific things '
    'a complete answer must mention"]}}\n\n'
    "key_concepts are matched against the candidate's answer to score it, so "
    "each one must be a specific term or phrase that appears in the material "
    "or follows directly from it. Never a vague label like \"understanding\", "
    '"the basics", or "key ideas" - those cannot be matched against an '
    "answer and make the score meaningless.\n\n"
    "Material:\n{excerpts}"
)

TOPICS_PROMPT_TEMPLATE = (
    "List the distinct topics this study material covers, in the order it "
    "covers them. These become the agenda for a mock interview, so each topic "
    "must be something a candidate could be asked a real question about.\n\n"
    "Respond with ONLY a JSON object matching this exact shape: "
    '{{"topics": ["short topic name", "another topic name"]}}\n\n'
    "Use between 3 and 10 topics. Keep each name under 60 characters.\n\n"
    "Material:\n{text}"
)


# ---------------------------------------------------------------------------
# The decision loop
# ---------------------------------------------------------------------------


class NextStep(BaseModel):
    """What the agent decided to do after an answer. `topic` is None only
    when the notebook produced no topic agenda at all, in which case
    questions are asked against the material as a whole."""

    topic: str | None
    is_probe: bool
    # Carried through so a probe's prompt can reference what the previous
    # answer missed, rather than re-deriving it in the question builder.
    probing_after: InterviewQA | None = None

    model_config = {"arbitrary_types_allowed": True}


def _is_weak(qa: InterviewQA) -> bool:
    return qa.score is not None and qa.score < settings.interview_low_score_threshold


def _consecutive_weak_on_topic(answered: Sequence[InterviewQA], topic: str | None) -> int:
    """Length of the run of weak answers on `topic` at the tail of the
    session. Counted from the end and stopped at the first answer that
    either changed topic or wasn't weak, so an earlier unrelated weak answer
    on the same topic can't inflate the streak and cut a probe short."""
    streak = 0
    for qa in reversed(answered):
        if qa.topic != topic or not _is_weak(qa):
            break
        streak += 1
    return streak


def decide_next_step(
    topics: Sequence[str],
    qa_items: Sequence[InterviewQA],
    question_limit: int,
) -> NextStep | None:
    """The agent's decision. Returns None when the interview should finish.

    Pure and synchronous on purpose: this is the behaviour that defines the
    feature, so it's testable directly against constructed turn histories
    with no LLM, no database, and no scoring model involved.
    """
    if len(qa_items) >= question_limit:
        return None

    answered = [qa for qa in qa_items if qa.answered_at is not None]
    last = answered[-1] if answered else None

    if last is not None and _is_weak(last):
        streak = _consecutive_weak_on_topic(answered, last.topic)
        if streak < settings.interview_max_consecutive_probes:
            # Probe: the answer revealed a gap, so dig into the same topic
            # before moving on. This is the branch that makes the interview
            # respond to the candidate rather than read from a list.
            return NextStep(topic=last.topic, is_probe=True, probing_after=last)
        # Two weak answers running on one topic. Probing further would burn
        # the remaining questions on material the candidate plainly hasn't
        # absorbed, so give up on it: it gets flagged as a weak area in the
        # report and the interview moves to new ground.
        logger.info("Interview: giving up on topic %r after %d weak answers", last.topic, streak)

    if not topics:
        # No agenda (very thin material, or overview generation never ran) -
        # keep asking against the notebook as a whole until the limit.
        return NextStep(topic=None, is_probe=False)

    covered = {qa.topic for qa in qa_items}
    for topic in topics:
        if topic not in covered:
            return NextStep(topic=topic, is_probe=False)

    # Every topic has been asked about at least once. Finishing here rather
    # than looping back for second passes keeps the interview's length
    # predictable and its report readable.
    return None


def summarize_session(topics: Sequence[str], qa_items: Sequence[InterviewQA]) -> tuple[int | None, list[str]]:
    """Overall score and flagged weak areas for the final report.

    A topic is weak when its answers *average* below the threshold, not when
    any single answer was weak: one bad answer on a topic the candidate
    otherwise handled well isn't a weak area, and flagging it would make the
    report noisy enough to ignore.
    """
    scored = [qa for qa in qa_items if qa.score is not None]
    if not scored:
        return None, []

    overall = round(sum(qa.score for qa in scored) / len(scored))

    by_topic: dict[str | None, list[int]] = {}
    for qa in scored:
        by_topic.setdefault(qa.topic, []).append(qa.score)

    weak = [
        topic
        for topic, scores in by_topic.items()
        if topic is not None and sum(scores) / len(scores) < settings.interview_low_score_threshold
    ]
    # Reported in agenda order rather than dict order, so the report reads in
    # the same sequence the interview ran.
    ordered = [topic for topic in topics if topic in weak]
    ordered.extend(topic for topic in weak if topic not in ordered)
    return overall, ordered


# ---------------------------------------------------------------------------
# LLM-backed question generation
# ---------------------------------------------------------------------------


async def _call_with_retry[T: BaseModel](client: LLMClient, prompt: str, schema: type[T]) -> T:
    last_detail = ""
    for _ in range(MAX_RETRIES):
        raw = await client.generate_json(prompt)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_detail = str(exc)
    raise InterviewError("invalid_llm_response", last_detail)


def _goal_clause(notebook: Notebook) -> str:
    """Reuses chat's goal hints (PRD 6.3) rather than keeping a second set:
    the user set one goal for the notebook, and every feature should read it
    the same way."""
    if notebook.goal_type is None:
        return ""
    hint = GOAL_PROMPT_HINTS[notebook.goal_type]
    if notebook.goal_type == GoalType.CUSTOM:
        hint = hint.format(description=notebook.goal_description or "not specified")
    return hint + "\n\n"


async def _ready_document_ids(session: AsyncSession, notebook_id: str) -> list[str]:
    result = await session.execute(
        select(Document.id).where(
            Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY
        )
    )
    return list(result.scalars().all())


async def _load_chunks(session: AsyncSession, notebook_id: str) -> list[Chunk]:
    result = await session.execute(
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def resolve_topics(
    notebook: Notebook, session: AsyncSession, client: LLMClient
) -> list[str]:
    """The interview's agenda.

    Prefers the notebook's own structured overview (PRD 6.2) - it already
    represents this material as a topic breakdown, and reusing it means the
    interview covers the same ground the user was shown up front rather than
    inventing a second, different view of their material. Falls back to one
    LLM call only when no overview is ready.
    """
    overview_result = await session.execute(
        select(Overview).where(
            Overview.notebook_id == notebook.id, Overview.status == OverviewStatus.READY
        )
    )
    overview = overview_result.scalar_one_or_none()
    if overview is not None and overview.topics_json:
        titles = [
            topic["title"]
            for topic in json.loads(overview.topics_json)
            if isinstance(topic, dict) and topic.get("title")
        ]
        if titles:
            return titles

    chunks = await _load_chunks(session, notebook.id)
    sections = build_sections(chunks)
    if not sections:
        raise InterviewError("no_content", "This notebook has no processed material to interview on.")

    try:
        result = await _call_with_retry(
            client, TOPICS_PROMPT_TEMPLATE.format(text=sections[0]), InterviewTopicsResult
        )
    except InterviewError:
        # An agenda is a nice-to-have, not a precondition: without one the
        # decision loop still works, asking against the material as a whole.
        # Failing the whole interview over it would be the wrong trade.
        logger.warning("Interview: topic agenda generation failed; continuing without an agenda")
        return []
    return [topic.strip() for topic in result.topics if topic.strip()]


def _retrieval_query(topic: str | None, notebook: Notebook, step: NextStep) -> str:
    parts: list[str] = []
    if topic:
        parts.append(topic)
    else:
        parts.append(notebook.name)
    if step.is_probe and step.probing_after is not None:
        missed = (
            json.loads(step.probing_after.missed_points_json)
            if step.probing_after.missed_points_json
            else []
        )
        # Retrieval is steered toward what the candidate actually missed, so a
        # probe pulls the passages covering the gap rather than the same
        # passages that produced the question they already failed.
        parts.extend(missed[:3])
    return " ".join(parts)


def _probe_clause(step: NextStep) -> str:
    if not step.is_probe or step.probing_after is None:
        return ""
    previous = step.probing_after
    missed = json.loads(previous.missed_points_json) if previous.missed_points_json else []
    missed_text = ", ".join(missed[:3]) if missed else "most of the expected detail"
    return (
        " The candidate just answered a question on this same topic poorly, "
        f"missing: {missed_text}. Ask a SIMPLER, more focused question on the "
        "same topic to find out what they do understand. Do not repeat the "
        f'previous question, which was: "{previous.question}"'
    )


async def _generate_question(
    notebook: Notebook,
    step: NextStep,
    session: AsyncSession,
    client: LLMClient,
    vector_store: VectorStore,
    focus: str | None,
) -> InterviewQuestionResult:
    document_ids = await _ready_document_ids(session, notebook.id)
    if not document_ids:
        raise InterviewError("no_content", "This notebook has no ready documents to interview on.")

    query = _retrieval_query(step.topic, notebook, step)
    # embed_texts inside query() is CPU-bound sync work - thread-offload it
    # the same way chat does, so one interview turn doesn't stall every other
    # concurrent request.
    hits = await asyncio.to_thread(
        vector_store.query,
        query,
        top_k=settings.interview_retrieval_top_k,
        document_ids=document_ids,
    )
    if hits:
        excerpts = "\n\n".join(hit.text for hit in hits)
    else:
        # Retrieval found nothing for this topic (possible when the agenda came
        # from an overview covering a document that has since been deleted).
        # Fall back to the material as a whole rather than prompting with an
        # empty excerpt block, which produced invented questions.
        chunks = await _load_chunks(session, notebook.id)
        sections = build_sections(chunks)
        if not sections:
            raise InterviewError("no_content", "This notebook has no processed material left.")
        excerpts = sections[0]

    topic_clause = f" Focus the question on this topic: {step.topic}." if step.topic else ""
    focus_clause = f" The candidate asked to focus on: {focus}." if focus else ""

    prompt = QUESTION_PROMPT_TEMPLATE.format(
        topic_clause=topic_clause,
        probe_clause=_probe_clause(step),
        focus_clause=focus_clause,
        goal_clause=_goal_clause(notebook),
        excerpts=excerpts,
    )
    return await _call_with_retry(client, prompt, InterviewQuestionResult)


def _default_client() -> LLMClient:
    return get_default_llm_client(ollama_timeout=settings.interview_llm_timeout_seconds)


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


async def start_interview(
    notebook: Notebook,
    options: InterviewStartRequest,
    session: AsyncSession,
    client: LLMClient | None = None,
    vector_store: VectorStore | None = None,
) -> tuple[InterviewSession, list[InterviewQA]]:
    """Creates a session, resolves the topic agenda, and asks the first
    question. Raises InterviewError / LLM errors to the caller - nothing is
    persisted if the first question can't be generated, so a failed start
    doesn't leave an empty session cluttering the notebook's history."""
    client = client or _default_client()
    vector_store = vector_store or get_vector_store()

    topics = await resolve_topics(notebook, session, client)

    interview = InterviewSession(
        notebook_id=notebook.id,
        mode=options.mode,
        status=InterviewStatus.IN_PROGRESS,
        question_limit=options.question_limit,
        topics_json=json.dumps(topics) if topics else None,
    )

    step = decide_next_step(topics, [], options.question_limit)
    if step is None:  # pragma: no cover - question_limit >= 3 makes this unreachable
        raise InterviewError("no_content", "Nothing to ask about in this notebook.")

    result = await _generate_question(notebook, step, session, client, vector_store, options.focus)

    # Persisted only now that the first question exists, so the two land in
    # the same commit and a notebook never shows a session with no questions.
    session.add(interview)
    await session.flush()
    first = InterviewQA(
        session_id=interview.id,
        question_index=0,
        topic=step.topic,
        question=result.question,
        ideal_answer=result.ideal_answer,
        key_concepts_json=json.dumps(result.key_concepts),
        is_probe=False,
    )
    session.add(first)
    await session.commit()
    await session.refresh(interview)
    return interview, [first]


async def submit_answer(
    notebook: Notebook,
    interview: InterviewSession,
    answer: str,
    session: AsyncSession,
    client: LLMClient | None = None,
    vector_store: VectorStore | None = None,
    embedder: Embedder | None = None,
) -> tuple[InterviewSession, list[InterviewQA]]:
    """Scores the pending answer, then advances the interview.

    The scored answer is committed BEFORE the next question is generated. If
    generation then fails (LLM down, invalid response), the user's answer and
    its feedback are already saved and the session sits in progress with no
    pending question - recoverable with `continue_interview`. Doing it in one
    commit would mean an LLM blip silently discarded work the user had
    already done.
    """
    if interview.status is InterviewStatus.COMPLETED:
        raise InterviewError("interview_completed", "This interview has already finished.")

    client = client or _default_client()
    vector_store = vector_store or get_vector_store()

    qa_items = await _load_qa(session, interview.id)
    pending = next((qa for qa in qa_items if qa.answered_at is None), None)
    if pending is None:
        raise InterviewError(
            "no_pending_question", "There's no question waiting to be answered in this interview."
        )

    key_concepts = json.loads(pending.key_concepts_json) if pending.key_concepts_json else []
    # score_answer embeds the answer, which is CPU-bound sync work - offloaded
    # for the same reason as retrieval above.
    scored = await asyncio.to_thread(
        score_answer,
        pending.question,
        answer,
        pending.ideal_answer,
        key_concepts,
        embedder,
    )

    pending.answer_text = answer
    pending.score = scored.score
    pending.feedback = scored.feedback
    pending.missed_points_json = json.dumps(scored.missed_points)
    pending.features_json = json.dumps(scored.features)
    pending.answered_at = datetime.now(UTC)
    await session.commit()

    qa_items = await _load_qa(session, interview.id)
    topics = json.loads(interview.topics_json) if interview.topics_json else []
    step = decide_next_step(topics, qa_items, interview.question_limit)

    if step is None:
        await _complete(interview, topics, qa_items, session)
        return interview, qa_items

    result = await _generate_question(notebook, step, session, client, vector_store, None)
    next_qa = InterviewQA(
        session_id=interview.id,
        question_index=len(qa_items),
        topic=step.topic,
        question=result.question,
        ideal_answer=result.ideal_answer,
        key_concepts_json=json.dumps(result.key_concepts),
        is_probe=step.is_probe,
    )
    session.add(next_qa)
    await session.commit()
    await session.refresh(interview)
    return interview, [*qa_items, next_qa]


async def continue_interview(
    notebook: Notebook,
    interview: InterviewSession,
    session: AsyncSession,
    client: LLMClient | None = None,
    vector_store: VectorStore | None = None,
) -> tuple[InterviewSession, list[InterviewQA]]:
    """Generates the next question for an in-progress session that has none
    pending. Exists so a failed question generation mid-interview is
    recoverable: the answer is already scored and saved, and this picks the
    interview back up instead of stranding it."""
    if interview.status is InterviewStatus.COMPLETED:
        raise InterviewError("interview_completed", "This interview has already finished.")

    client = client or _default_client()
    vector_store = vector_store or get_vector_store()

    qa_items = await _load_qa(session, interview.id)
    if any(qa.answered_at is None for qa in qa_items):
        # Already has a question waiting - nothing to do, and generating
        # another would queue two unanswered questions.
        return interview, qa_items

    topics = json.loads(interview.topics_json) if interview.topics_json else []
    step = decide_next_step(topics, qa_items, interview.question_limit)
    if step is None:
        await _complete(interview, topics, qa_items, session)
        return interview, qa_items

    result = await _generate_question(notebook, step, session, client, vector_store, None)
    next_qa = InterviewQA(
        session_id=interview.id,
        question_index=len(qa_items),
        topic=step.topic,
        question=result.question,
        ideal_answer=result.ideal_answer,
        key_concepts_json=json.dumps(result.key_concepts),
        is_probe=step.is_probe,
    )
    session.add(next_qa)
    await session.commit()
    await session.refresh(interview)
    return interview, [*qa_items, next_qa]


async def end_interview(
    interview: InterviewSession, session: AsyncSession
) -> tuple[InterviewSession, list[InterviewQA]]:
    """Ends an interview early. The report is built from whatever was
    answered, so stopping after three of eight questions still produces a
    real report rather than nothing."""
    qa_items = await _load_qa(session, interview.id)
    if interview.status is InterviewStatus.COMPLETED:
        return interview, qa_items
    topics = json.loads(interview.topics_json) if interview.topics_json else []
    await _complete(interview, topics, qa_items, session)
    return interview, qa_items


async def _complete(
    interview: InterviewSession,
    topics: Sequence[str],
    qa_items: Sequence[InterviewQA],
    session: AsyncSession,
) -> None:
    overall, weak_areas = summarize_session(topics, qa_items)
    interview.status = InterviewStatus.COMPLETED
    interview.overall_score = overall
    interview.weak_areas_json = json.dumps(weak_areas) if weak_areas else None
    interview.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(interview)


async def _load_qa(session: AsyncSession, interview_id: str) -> list[InterviewQA]:
    result = await session.execute(
        select(InterviewQA)
        .where(InterviewQA.session_id == interview_id)
        .order_by(InterviewQA.question_index)
    )
    return list(result.scalars().all())


async def load_qa_items(session: AsyncSession, interview_id: str) -> list[InterviewQA]:
    """Public read used by the router to build a response for a session it
    didn't just mutate."""
    return await _load_qa(session, interview_id)


async def latest_session_for_notebook(
    session: AsyncSession, notebook_id: str
) -> InterviewSession | None:
    result = await session.execute(
        select(InterviewSession)
        .where(InterviewSession.notebook_id == notebook_id)
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def in_progress_session_for_notebook(
    session: AsyncSession, notebook_id: str
) -> InterviewSession | None:
    result = await session.execute(
        select(InterviewSession)
        .where(
            InterviewSession.notebook_id == notebook_id,
            InterviewSession.status == InterviewStatus.IN_PROGRESS,
        )
        .order_by(InterviewSession.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


__all__ = [
    "InterviewMode",
    "NextStep",
    "continue_interview",
    "decide_next_step",
    "end_interview",
    "in_progress_session_for_notebook",
    "latest_session_for_notebook",
    "load_qa_items",
    "resolve_topics",
    "start_interview",
    "submit_answer",
    "summarize_session",
]

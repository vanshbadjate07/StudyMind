import asyncio
import json
import re

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    ChatMessage,
    ChatRole,
    Document,
    DocumentStatus,
    GoalType,
    Notebook,
    Overview,
    OverviewStatus,
)
from app.services.llm_client import LLMClient, get_default_llm_client
from app.services.vector_store import VectorSearchResult, VectorStore, get_vector_store

GOAL_PROMPT_HINTS: dict[GoalType, str] = {
    GoalType.EXAM: (
        "The user is studying this material to prepare for an exam — "
        "prioritize accuracy and the kind of detail they'd be tested on."
    ),
    GoalType.INTERVIEW: (
        "The user is studying this material to prepare for an interview — "
        "keep answers practical and focused on what they'd need to explain confidently."
    ),
    GoalType.SKILL: (
        "The user is learning this as a new skill — favor clear, approachable explanations."
    ),
    GoalType.EXPLORATION: (
        "The user is exploring this material out of curiosity — keep answers engaging, not overly formal."
    ),
    GoalType.CUSTOM: "The user's goal: {description}",
}

GROUNDED_PROMPT_TEMPLATE = (
    "You are a study assistant helping the user understand their own uploaded "
    "material. The excerpts below are real passages retrieved from the user's "
    "documents because they matched the question — but retrieval works on "
    "approximate similarity, not certainty, so read them and judge for "
    "yourself whether they actually address the question before answering. "
    "Answer using ONLY these excerpts; do not add outside knowledge, even if "
    "you know more about the topic than they say.{internet_clause}\n\n"
    "{goal_clause}"
    "Excerpts from the user's material:\n{excerpts}\n\n"
    "{history_clause}"
    "Question: {question}\n\n"
    "Instructions:\n"
    "- Answer clearly and directly in plain prose. Use a bullet list only if "
    "the question specifically asks for one.\n"
    "- If the excerpts only partially answer the question, answer the part "
    "they do cover and say plainly what's missing — don't fill the gap by "
    "guessing.\n"
    "- If the excerpts don't actually address the question at all, say so as "
    "your first sentence instead of guessing from memory."
)

# Used whenever retrieval didn't find a specific passage closely matching the
# question. This still ALWAYS gets a real model-generated answer, not a fixed
# string — the strict per-fact grounding in GROUNDED_PROMPT_TEMPLATE exists to
# stop factual hallucination, but a plain greeting or a general "what's this
# about" question isn't a factual claim to hallucinate; it's exactly what the
# notebook's own overview already answers. Giving the model that overview as
# context (when one exists) keeps the same honesty guarantee — it can only
# draw on real, already-generated material — while letting ordinary
# conversation and summary-style questions actually get answered.
NO_MATCH_PROMPT_TEMPLATE = (
    "You are a study assistant for the user's uploaded material. A search for a "
    "specific passage matching this question didn't turn up a close result — "
    "so you have a general summary of the material below, but not a specific "
    "excerpt to quote from.\n\n"
    "{overview_clause}"
    "{goal_clause}"
    "{history_clause}"
    "Question: {question}\n\n"
    "Instructions — figure out which case this is, then follow it:\n"
    "- Greeting or general conversation (e.g. \"hi\", \"what can you help with\"): "
    "respond naturally and briefly.\n"
    "- General question about the material itself (what it covers, a summary): "
    "answer using the summary above, when one is available.\n"
    "- A specific fact or detail the summary doesn't contain:{internet_instruction}"
)

# Unlike the removed NOT_COVERED_MESSAGE (a canned reply that stood in for a
# real per-question answer even when material existed to answer from), this
# is a fixed system message for one exact, fully deterministic state: zero
# ready documents in the notebook at all, so there is nothing to generate an
# answer *from* — the same category as DocumentList's "No documents yet"
# empty state, not a hardcoded topic answer. It exists because instructing
# the model not to answer from its own training knowledge turned out to be
# unreliable on the small local model this app runs (qwen2.5:3b): asked
# "what is MongoDB?" in a brand-new notebook with zero uploads and internet
# mode off, it answered confidently from memory anyway, defeating the whole
# point of the toggle. Skipping the LLM call entirely for this one state is
# the only way to guarantee it can't happen — internet mode still bypasses
# this and lets the model answer freely, since that's what the toggle is for.
NO_DOCUMENTS_MESSAGE = (
    "This notebook doesn't have any documents yet, so there's nothing for me to answer from. "
    "Upload a PDF to get started, or turn on internet mode for general-knowledge answers instead."
)

MAX_CITATIONS = 5


def _internet_clause(internet_mode: bool) -> str:
    if not internet_mode:
        return ""
    return (
        " Exception: internet mode is on, so you may add relevant general "
        "knowledge beyond these excerpts too — but clearly mark when you're "
        'doing so (for example: "Beyond your notes, ...").'
    )


def _internet_instruction(internet_mode: bool) -> str:
    if internet_mode:
        return (
            " answer using your own general knowledge instead, and clearly note "
            "that it's beyond what's in their material (for example: \"This isn't "
            'in your uploaded material, but...").'
        )
    return (
        " say plainly that this isn't covered in your uploaded material rather "
        "than guessing — you can suggest they rephrase, upload more material, or "
        "turn on internet mode for a general-knowledge answer."
    )


def _goal_clause(notebook: Notebook) -> str:
    if notebook.goal_type is None:
        return ""
    hint = GOAL_PROMPT_HINTS[notebook.goal_type]
    if notebook.goal_type == GoalType.CUSTOM:
        hint = hint.format(description=notebook.goal_description or "not specified")
    return hint + "\n\n"


def _overview_clause(overview: Overview | None) -> str:
    if overview is None or not overview.short_summary:
        return "This notebook doesn't have any processed material yet.\n\n"
    return f"General summary of this notebook's material:\n{overview.short_summary}\n\n"


def _history_clause(history: list[ChatMessage]) -> str:
    if not history:
        return ""
    lines = [f"{'User' if m.role == ChatRole.USER else 'Assistant'}: {m.content}" for m in history]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


# Phrases the model uses when it recognizes, mid-answer, that the excerpts
# it was given don't actually address the question — this can happen even
# though those excerpts individually cleared the vector-distance relevance
# threshold, because "close enough by distance" isn't the same guarantee as
# "actually relevant to this specific question." Checked only against the
# answer's FIRST SENTENCE (not just its opening characters — a short
# sentence can still fit an unrelated caveat within a fixed-length window):
# a refusal phrase appearing there means the answer opens by rejecting the
# question outright (as in the reported case — a Python-looping question
# against combinatorial-testing excerpts), not a caveat folded into a later
# sentence of an otherwise-substantive answer that legitimately used the
# material (e.g. "X works like this. The excerpts don't cover Y, though.").
_REFUSAL_MARKERS = (
    "do not contain",
    "does not contain",
    "doesn't contain",
    "don't contain",
    "no information about",
    "not contain any information",
    "cannot provide an answer",
    "unrelated to",
    "not related to",
    "isn't covered",
    "is not covered",
    "aren't covered",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _is_unfounded_refusal(answer: str) -> bool:
    first_sentence = _SENTENCE_BOUNDARY.split(answer.strip(), maxsplit=1)[0].lower()
    return any(marker in first_sentence for marker in _REFUSAL_MARKERS)


def _format_excerpts(hits: list[VectorSearchResult], filenames: dict[str, str]) -> str:
    parts = []
    for hit in hits:
        filename = filenames.get(hit.document_id, "your document")
        source = f"{filename}, page {hit.page_number}" if hit.page_number else filename
        parts.append(f"[Source: {source}]\n{hit.text}")
    return "\n\n".join(parts)


def _build_citations(hits: list[VectorSearchResult], filenames: dict[str, str]) -> list[dict]:
    seen: set[tuple[str, int | None]] = set()
    citations: list[dict] = []
    for hit in hits:
        key = (hit.document_id, hit.page_number)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "document_id": hit.document_id,
                "filename": filenames.get(hit.document_id, "your document"),
                "page_number": hit.page_number,
            }
        )
        if len(citations) >= MAX_CITATIONS:
            break
    return citations


async def ask_question(
    notebook: Notebook,
    question: str,
    internet_mode: bool,
    session: AsyncSession,
    vector_store: VectorStore | None = None,
    client: LLMClient | None = None,
) -> ChatMessage:
    """Answers one question against a notebook's material, persisting both
    the user's question and the assistant's reply. With at least one ready
    document, the LLM is always called — there's no fixed canned reply — but
    what it's given and told to do depends on retrieval quality: a
    specific-passage match (grounded, decided by vector distance against a
    calibrated threshold, not by asking the LLM to self-report) gets those
    excerpts and a strict "answer only from this" instruction; anything else
    (a broad question, a greeting, or a genuine gap in the material) gets the
    notebook's own overview as context plus an honest-fallback instruction.
    With zero ready documents and internet mode off, the LLM isn't called at
    all (see NO_DOCUMENTS_MESSAGE) — that's the one case where trusting the
    model's own restraint isn't good enough. A distance threshold can still
    let through excerpts that are close enough numerically but not actually
    relevant to this specific question — see _is_unfounded_refusal, which
    catches the model's own "these excerpts don't cover that" response and
    strips the citations/grounded flag rather than presenting a refusal as
    if it were a sourced answer.

    Raises LLMUnreachableError / LLMTimeoutError if the LLM call fails — the
    caller decides how to surface that; the user's question is already
    persisted by that point regardless."""
    vector_store = vector_store or get_vector_store()
    client = client or get_default_llm_client(
        ollama_model=settings.chat_model,
        ollama_timeout=settings.chat_llm_timeout_seconds,
        ollama_num_ctx=settings.chat_context_tokens,
    )

    history_result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.notebook_id == notebook.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(settings.chat_history_messages)
    )
    history = list(reversed(history_result.scalars().all()))

    user_message = ChatMessage(notebook_id=notebook.id, role=ChatRole.USER, content=question)
    session.add(user_message)
    await session.commit()

    doc_result = await session.execute(
        select(Document).where(Document.notebook_id == notebook.id, Document.status == DocumentStatus.READY)
    )
    ready_documents = list(doc_result.scalars().all())
    filenames = {doc.id: doc.filename for doc in ready_documents}

    if not ready_documents and not internet_mode:
        assistant_message = ChatMessage(
            notebook_id=notebook.id, role=ChatRole.ASSISTANT, content=NO_DOCUMENTS_MESSAGE
        )
        session.add(assistant_message)
        await session.commit()
        await session.refresh(assistant_message)
        return assistant_message

    hits: list[VectorSearchResult] = []
    if ready_documents:
        # embed_texts (inside vector_store.query) is CPU-bound sync work,
        # same as processing_pipeline's extraction/embedding — thread-offload
        # so one slow chat question doesn't stall every other concurrent
        # request (health checks, document polling, other notebooks).
        hits = await asyncio.to_thread(
            vector_store.query,
            question,
            top_k=settings.chat_top_k,
            document_ids=[doc.id for doc in ready_documents],
        )
    # Only hits that individually clear the relevance bar are usable — the
    # top hit clearing it just means *something* relevant exists, not that
    # every retrieved chunk is. Without this, a grounded answer could still
    # cite (or be prompted with) a chunk from a completely unrelated part of
    # the notebook, e.g. a biology answer citing a page about basketball.
    relevant_hits = [
        hit for hit in hits if hit.distance <= settings.chat_relevance_distance_threshold
    ]
    grounded = bool(relevant_hits)

    if grounded:
        prompt = GROUNDED_PROMPT_TEMPLATE.format(
            internet_clause=_internet_clause(internet_mode),
            goal_clause=_goal_clause(notebook),
            excerpts=_format_excerpts(relevant_hits, filenames),
            history_clause=_history_clause(history),
            question=question,
        )
        citations = _build_citations(relevant_hits, filenames)
        used_internet = False
    else:
        overview_result = await session.execute(
            select(Overview).where(
                Overview.notebook_id == notebook.id, Overview.status == OverviewStatus.READY
            )
        )
        overview = overview_result.scalar_one_or_none()
        prompt = NO_MATCH_PROMPT_TEMPLATE.format(
            overview_clause=_overview_clause(overview),
            goal_clause=_goal_clause(notebook),
            history_clause=_history_clause(history),
            question=question,
            internet_instruction=_internet_instruction(internet_mode),
        )
        citations = []
        used_internet = internet_mode

    answer = await client.generate_text(prompt)

    if grounded and _is_unfounded_refusal(answer):
        # The distance threshold said the top hits were close enough to be
        # usable, but "close enough by distance" and "actually answers this
        # question" aren't the same thing — the model noticed the mismatch
        # and said so in its own answer (e.g. "these excerpts don't cover
        # Python looping, they're about combinatorial testing"). Trust that
        # over the retrieval signal: don't attach citations, or claim
        # grounding, for material the answer explicitly says it didn't use.
        grounded = False
        citations = []

    assistant_message = ChatMessage(
        notebook_id=notebook.id,
        role=ChatRole.ASSISTANT,
        content=answer,
        citations_json=json.dumps(citations) if citations else None,
        grounded=grounded,
        used_internet=used_internet,
    )
    session.add(assistant_message)
    await session.commit()
    await session.refresh(assistant_message)
    return assistant_message


async def edit_question(
    notebook: Notebook,
    target: ChatMessage,
    question: str,
    internet_mode: bool,
    session: AsyncSession,
    vector_store: VectorStore | None = None,
    client: LLMClient | None = None,
) -> ChatMessage:
    """Edits a past question in place, the way Claude/ChatGPT do it: the
    edited question becomes the new end of the conversation, and everything
    after it — its old answer, and any later back-and-forth — is discarded
    rather than kept as an orphaned branch, since this app has no UI for
    multiple conversation branches. Re-asks through ask_question so
    grounding, retries, and persistence all behave identically to a fresh
    question. Callers must have already verified `target` belongs to this
    notebook and is a user message."""
    await session.execute(
        delete(ChatMessage).where(
            ChatMessage.notebook_id == notebook.id,
            or_(
                ChatMessage.created_at > target.created_at,
                and_(ChatMessage.created_at == target.created_at, ChatMessage.id >= target.id),
            ),
        )
    )
    await session.commit()
    return await ask_question(notebook, question, internet_mode, session, vector_store, client)

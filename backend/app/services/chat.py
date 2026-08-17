import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ChatMessage, ChatRole, Document, DocumentStatus, GoalType, Notebook
from app.services.ollama_client import OllamaClient
from app.services.vector_store import VectorSearchResult, VectorStore, get_vector_store

NOT_COVERED_MESSAGE = (
    "I couldn't find anything about this in your uploaded material. Try "
    "rephrasing your question, or turn on internet mode for a "
    "general-knowledge answer instead."
)

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
    "You are a study assistant answering a question about the user's uploaded "
    "material. Base your answer on the excerpts below, which come from the "
    "user's own documents.{internet_clause}\n\n"
    "{goal_clause}"
    "Excerpts from the user's material:\n{excerpts}\n\n"
    "{history_clause}"
    "Question: {question}\n\n"
    "Answer clearly and directly in plain prose (no bullet points unless the "
    "question specifically asks for a list). If the excerpts only partially "
    "answer the question, say what's missing rather than guessing."
)

UNGROUNDED_PROMPT_TEMPLATE = (
    "You are a study assistant. The user's uploaded material does not appear "
    "to cover this question. Answer using your own general knowledge, and "
    "start your answer by clearly noting that this isn't covered in their "
    'material (for example: "This isn\'t covered in your uploaded material, '
    'but...").\n\n'
    "{history_clause}"
    "Question: {question}\n\n"
    "Answer clearly and directly in plain prose."
)

MAX_CITATIONS = 5


def _internet_clause(internet_mode: bool) -> str:
    if not internet_mode:
        return ""
    return (
        " You may also add relevant general knowledge beyond these excerpts, "
        'but clearly say when you\'re doing so (for example: "Beyond your notes, ...").'
    )


def _goal_clause(notebook: Notebook) -> str:
    if notebook.goal_type is None:
        return ""
    hint = GOAL_PROMPT_HINTS[notebook.goal_type]
    if notebook.goal_type == GoalType.CUSTOM:
        hint = hint.format(description=notebook.goal_description or "not specified")
    return hint + "\n\n"


def _history_clause(history: list[ChatMessage]) -> str:
    if not history:
        return ""
    lines = [f"{'User' if m.role == ChatRole.USER else 'Assistant'}: {m.content}" for m in history]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


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
    client: OllamaClient | None = None,
) -> ChatMessage:
    """Answers one question against a notebook's material, persisting both
    the user's question and the assistant's reply. Grounding is decided by
    retrieval quality (the best match's vector distance against a
    calibrated threshold), not by asking the LLM to self-report whether it
    used the material — a small local model can't be trusted to police that
    honestly, but the retrieval score can. If nothing relevant is found and
    internet mode is off, the LLM isn't even called: a fixed, honest refusal
    is used instead, which can never hallucinate.

    Raises OllamaUnreachableError / OllamaTimeoutError if the LLM call fails
    (only reachable when grounded, or when internet_mode allows an
    ungrounded answer) — the caller decides how to surface that; the user's
    question is already persisted by that point regardless."""
    vector_store = vector_store or get_vector_store()
    client = client or OllamaClient(
        model=settings.chat_model,
        timeout=settings.chat_llm_timeout_seconds,
        num_ctx=settings.chat_context_tokens,
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
        answer = await client.generate_text(prompt)
        citations = _build_citations(relevant_hits, filenames)
        used_internet = False
    elif internet_mode:
        prompt = UNGROUNDED_PROMPT_TEMPLATE.format(
            history_clause=_history_clause(history), question=question
        )
        answer = await client.generate_text(prompt)
        citations = []
        used_internet = True
    else:
        answer = NOT_COVERED_MESSAGE
        citations = []
        used_internet = False

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

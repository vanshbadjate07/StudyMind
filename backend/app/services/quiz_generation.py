import json
import re

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import QuizGenerationError
from app.models import Chunk, Document, DocumentStatus, Notebook, Quiz, QuizStatus
from app.schemas import QuizDifficulty, QuizGenerateRequest, QuizGenerationResult, QuizQuestionResult
from app.services.ollama_client import OllamaClient, OllamaTimeoutError, OllamaUnreachableError

MAX_RETRIES = 2

DEFAULT_OPTIONS = QuizGenerateRequest()

_DIFFICULTY_CLAUSES: dict[QuizDifficulty, str] = {
    QuizDifficulty.EASY: (
        " Keep every question straightforward — testing recall of a clearly-stated "
        "fact, term, or definition, not multi-step reasoning."
    ),
    QuizDifficulty.MEDIUM: (
        " Mix in questions that require connecting two related ideas from the "
        "material, not just recalling a single stated fact."
    ),
    QuizDifficulty.HARD: (
        " Favor questions that require applying or reasoning about the material — "
        "working through an example, comparing two concepts, or spotting a subtle "
        "distinction — rather than recalling a fact stated outright."
    ),
    QuizDifficulty.MIXED: (
        " Vary the difficulty across questions — some straightforward recall, some "
        "that require connecting ideas or reasoning about the material."
    ),
}

QUIZ_PROMPT_TEMPLATE = (
    "You are writing a multiple-choice quiz to test understanding of this "
    "study material. Write exactly {count} questions.{knowledge_clause}"
    "{difficulty_clause}{focus_clause}\n\n"
    "Respond with ONLY a JSON object matching this exact shape: "
    '{{"questions": [{{"question": "string", '
    '"options": ["string", "string", "string", "string"], '
    '"correct_index": integer (0-3 — the index into options above of the '
    'correct one), "explanation": "1-2 sentences, grounded in the material, '
    'explaining why that answer is correct"}}]}}.\n\n'
    "Each question's four options should be plausible and similar in length "
    "and specificity — avoid options that are obviously wrong just from how "
    "they're phrased, and vary which position (0-3) holds the correct answer "
    "across questions rather than always using the same one. The four options "
    "must be four genuinely different answers — never list the same real-world "
    "thing twice under different spelling, capitalization, or naming.\n\n"
    "Material:\n{text}"
)


def _knowledge_clause(allow_general_knowledge: bool) -> str:
    if allow_general_knowledge:
        return (
            " Prefer the material below, but where it's thin you may draw on your "
            "own general knowledge of the subject to round out the quiz — just "
            "keep every question relevant to what this material covers."
        )
    return (
        " Every question must be answerable directly from the material below — "
        "do not test outside knowledge, and do not invent facts the material "
        "doesn't state."
    )


def _focus_clause(focus: str | None) -> str:
    if not focus:
        return ""
    return (
        f" Focus especially on: {focus}. If a given excerpt isn't really about "
        "that focus, write good general questions from it instead of forcing an "
        "unrelated connection."
    )


async def generate_quiz(
    notebook_id: str,
    session: AsyncSession,
    client: OllamaClient | None = None,
    *,
    options: QuizGenerateRequest = DEFAULT_OPTIONS,
) -> None:
    """Runs section-building -> per-section question generation for one
    notebook's quiz, always resolving its Quiz row to READY or FAILED. Never
    raises — this is called from a background task with nothing to report an
    exception to. The quiz router's generate endpoint already creates/resets
    the Quiz row to PENDING (in its own request-scoped session, separate
    from the one this background task uses), but this still gets-or-creates
    defensively so the function is correct standing alone too — unlike
    overview generation, quiz generation is only ever user-triggered (never
    automatically from concurrent document-processing completions), so
    there's no concurrent-create race here and no need for a per-notebook
    lock the way overview needs one."""
    try:
        await _generate_quiz_body(
            notebook_id,
            session,
            client or OllamaClient(timeout=settings.quiz_llm_timeout_seconds),
            options,
        )
    except Exception as exc:
        try:
            await _mark_failed(session, notebook_id, "generation_error", str(exc))
        except Exception:
            pass


async def _generate_quiz_body(
    notebook_id: str, session: AsyncSession, client: OllamaClient, options: QuizGenerateRequest
) -> None:
    if await session.get(Notebook, notebook_id) is None:
        return

    quiz = await _get_or_create_quiz(session, notebook_id)
    if quiz is None:
        return

    # Re-check after the (possibly retried) create — the notebook could have
    # been deleted in the window above.
    if await session.get(Notebook, notebook_id) is None:
        return

    quiz.status = QuizStatus.GENERATING
    await session.commit()

    try:
        chunks = await _load_chunks(session, notebook_id)
        sections = _build_sections(chunks)
        if not sections:
            raise QuizGenerationError("no_content", "Notebook has no ready documents to quiz on.")

        questions = await _generate_questions(client, sections, options)
        if not questions:
            raise QuizGenerationError("invalid_llm_response", "No valid questions were generated.")

        if await session.get(Notebook, notebook_id) is None:
            return  # deleted while the LLM call(s) were running; nothing to persist

        await _mark_ready(session, notebook_id, questions)
    except QuizGenerationError as exc:
        await _mark_failed(session, notebook_id, exc.reason, exc.detail)
    except OllamaUnreachableError as exc:
        await _mark_failed(session, notebook_id, "ollama_unreachable", str(exc))
    except OllamaTimeoutError as exc:
        await _mark_failed(session, notebook_id, "ollama_timeout", str(exc))


def _build_sections(chunks: list[Chunk]) -> list[str]:
    """Same splitting strategy as overview_generation._build_sections
    (reuses its sizing settings) — small notebooks get a single section (one
    LLM call), larger ones are split so each stays under
    overview_max_section_chars, capped at overview_max_sections total."""
    if not chunks:
        return []

    total_chars = sum(len(chunk.text) for chunk in chunks)
    if total_chars <= settings.overview_single_pass_char_budget:
        return ["\n\n".join(chunk.text for chunk in chunks)]

    sections: list[str] = []
    current: list[str] = []
    current_chars = 0
    for chunk in chunks:
        would_exceed_cap = current_chars + len(chunk.text) > settings.overview_max_section_chars
        under_section_limit = len(sections) < settings.overview_max_sections - 1
        if current and would_exceed_cap and under_section_limit:
            sections.append("\n\n".join(current))
            current = []
            current_chars = 0
        current.append(chunk.text)
        current_chars += len(chunk.text)
    if current:
        sections.append("\n\n".join(current))
    return sections


_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]")


def _normalize_option(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form used only to catch two
    options naming the same thing (e.g. "Llama" vs "LLaMA") — not a general
    semantic-similarity check, just enough to catch the exact failure mode
    observed: the model offering the same real-world answer twice under
    different capitalization, with one arbitrarily marked correct and the
    other arbitrarily marked wrong."""
    return _NON_ALPHANUMERIC.sub("", text.lower())


def _has_duplicate_options(question: QuizQuestionResult) -> bool:
    normalized = [_normalize_option(option) for option in question.options]
    return len(set(normalized)) != len(normalized)


def _drop_duplicate_option_questions(questions: list[QuizQuestionResult]) -> list[QuizQuestionResult]:
    """The prompt instructs against this, but the small local model doesn't
    always comply — belt and suspenders, same reasoning as chat.py's
    _is_unfounded_refusal: a prompt instruction alone isn't a guarantee, so
    anything that would show the user two options for the same real answer
    (one arbitrarily "correct", one arbitrarily "wrong") is filtered out
    here rather than trusted to never happen. Dropping bad questions instead
    of failing the whole batch means one bad question just means slightly
    fewer than requested, not a failed generation."""
    return [q for q in questions if not _has_duplicate_options(q)]


async def _generate_questions(
    client: OllamaClient, sections: list[str], options: QuizGenerateRequest
) -> list[QuizQuestionResult]:
    target = options.question_count
    knowledge_clause = _knowledge_clause(options.allow_general_knowledge)
    difficulty_clause = _DIFFICULTY_CLAUSES[options.difficulty]
    focus_clause = _focus_clause(options.focus)

    if len(sections) == 1:
        prompt = QUIZ_PROMPT_TEMPLATE.format(
            count=target,
            knowledge_clause=knowledge_clause,
            difficulty_clause=difficulty_clause,
            focus_clause=focus_clause,
            text=sections[0],
        )
        result = await _call_with_retry(client, prompt, QuizGenerationResult)
        return _drop_duplicate_option_questions(result.questions)[:target]

    # ceil(target / num_sections) per section, so a notebook with more
    # sections than questions still gets at least one question from each.
    per_section = max(1, -(-target // len(sections)))
    all_questions: list[QuizQuestionResult] = []
    for section in sections:
        prompt = QUIZ_PROMPT_TEMPLATE.format(
            count=per_section,
            knowledge_clause=knowledge_clause,
            difficulty_clause=difficulty_clause,
            focus_clause=focus_clause,
            text=section,
        )
        result = await _call_with_retry(client, prompt, QuizGenerationResult)
        all_questions.extend(_drop_duplicate_option_questions(result.questions))
    return all_questions[:target]


async def _call_with_retry[T: BaseModel](client: OllamaClient, prompt: str, schema: type[T]) -> T:
    last_detail = ""
    for _ in range(MAX_RETRIES):
        raw = await client.generate_json(prompt)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_detail = str(exc)
    raise QuizGenerationError("invalid_llm_response", last_detail)


async def _get_or_create_quiz(session: AsyncSession, notebook_id: str) -> Quiz | None:
    existing = await _get_quiz(session, notebook_id)
    if existing is not None:
        return existing

    quiz = Quiz(notebook_id=notebook_id, status=QuizStatus.PENDING)
    session.add(quiz)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent create for the same notebook
        # (notebook_id is unique) — use the row the other call created.
        await session.rollback()
        return await _get_quiz(session, notebook_id)
    await session.refresh(quiz)
    return quiz


async def _load_chunks(session: AsyncSession, notebook_id: str) -> list[Chunk]:
    result = await session.execute(
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def _mark_ready(session: AsyncSession, notebook_id: str, questions: list[QuizQuestionResult]) -> None:
    quiz = await _get_quiz(session, notebook_id)
    if quiz is None:
        return
    quiz.status = QuizStatus.READY
    quiz.questions_json = json.dumps([q.model_dump() for q in questions])
    quiz.error_reason = None
    quiz.error_detail = None
    await session.commit()


async def _mark_failed(session: AsyncSession, notebook_id: str, reason: str, detail: str) -> None:
    await session.rollback()
    quiz = await _get_quiz(session, notebook_id)
    if quiz is None:
        return
    quiz.status = QuizStatus.FAILED
    quiz.error_reason = reason
    quiz.error_detail = detail or None
    await session.commit()


async def _get_quiz(session: AsyncSession, notebook_id: str) -> Quiz | None:
    result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
    return result.scalar_one_or_none()

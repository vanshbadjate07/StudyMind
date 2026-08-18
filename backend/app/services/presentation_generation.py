import json
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import PresentationGenerationError
from app.models import Chunk, Document, DocumentStatus, Notebook, Presentation, PresentationStatus
from app.schemas import (
    PresentationGenerateRequest,
    PresentationGenerationResult,
    PresentationStyle,
    SlideLayout,
    SlideResult,
)
from app.services.llm_client import LLMClient, get_default_llm_client
from app.services.llm_errors import LLMTimeoutError, LLMUnreachableError
from app.services.presentation_renderer import render_presentation
from app.services.section_splitting import build_sections

MAX_RETRIES = 2

DEFAULT_OPTIONS = PresentationGenerateRequest()

_STYLE_CLAUSES: dict[PresentationStyle, str] = {
    PresentationStyle.CONCISE: (
        " Keep bullet counts low (3-4 per slide) and favor only the most "
        "essential points — this deck should be quick to read, not exhaustive."
    ),
    PresentationStyle.EXAM_FOCUSED: (
        " Prioritize the facts, definitions, and distinctions most likely to "
        "be tested, phrased precisely rather than loosely."
    ),
    PresentationStyle.VISUAL_HEAVY: (
        " Favor two_column and comparison layouts over plain bullets wherever "
        "the material allows it, to maximize visual variety across the deck."
    ),
}

PRESENTATION_PROMPT_TEMPLATE = (
    "You are structuring a presentation slide deck from this study material. "
    "Produce exactly {count} body slides (not counting the title slide, which "
    "is added separately) in a logical order that builds understanding "
    "progressively.{style_clause}{focus_clause}\n\n"
    "Respond with ONLY a JSON object matching this exact shape: "
    '{{"slides": [{{"layout": "bullets" | "two_column" | "quote" | "comparison", '
    '"title": "string (slide heading; not shown for quote layout)", '
    '"lines": ["string", ...] (bullets layout only: 3-6 short punchy bullet points), '
    '"columns": [{{"heading": "string", "lines": ["string", ...]}}, '
    '{{"heading": "string", "lines": ["string", ...]}}] '
    "(two_column and comparison layouts only: exactly 2 columns), "
    '"quote": "string" (quote layout only: one striking sentence pulled or '
    "closely paraphrased from the material), "
    '"attribution": "string or null" (quote layout only: what concept or '
    "section this idea comes from in the material; omit if there's no natural one)"
    "}}]}}.\n\n"
    'Never use a "title" layout — that slide is added separately. Vary which '
    'layout you use across slides rather than making every slide "bullets" — '
    "use two_column or comparison when the material naturally contrasts two "
    "things, and quote for a single memorable statement. Every slide's "
    "content must come from the material below — do not invent facts. Bullet "
    "lines must be short and punchy (under 15 words each), not full "
    "paragraphs — this is a slide, not a document.\n\n"
    "Material:\n{text}"
)


def _style_clause(style: PresentationStyle) -> str:
    return _STYLE_CLAUSES[style]


def _focus_clause(focus: str | None) -> str:
    if not focus:
        return ""
    return (
        f" Focus especially on: {focus}. If a given excerpt isn't really about "
        "that focus, write good general slides from it instead of forcing an "
        "unrelated connection."
    )


async def generate_presentation(
    notebook_id: str,
    session: AsyncSession,
    client: LLMClient | None = None,
    *,
    options: PresentationGenerateRequest = DEFAULT_OPTIONS,
) -> None:
    """Runs section-building -> slide-plan generation -> rendering for one
    notebook's presentation, always resolving its Presentation row to READY
    or FAILED. Never raises — called from a background task with nothing to
    report an exception to. User-triggered only (never automatic), so no
    per-notebook lock is needed — same reasoning as quiz generation."""
    try:
        await _generate_presentation_body(
            notebook_id,
            session,
            client or get_default_llm_client(ollama_timeout=settings.presentation_llm_timeout_seconds),
            options,
        )
    except Exception as exc:
        try:
            await _mark_failed(session, notebook_id, "generation_error", str(exc))
        except Exception:
            pass


async def _generate_presentation_body(
    notebook_id: str, session: AsyncSession, client: LLMClient, options: PresentationGenerateRequest
) -> None:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None:
        return

    presentation = await _get_or_create_presentation(session, notebook_id)
    if presentation is None:
        return

    notebook = await session.get(Notebook, notebook_id)  # re-check after the (possibly retried) create
    if notebook is None:
        return

    presentation.status = PresentationStatus.GENERATING
    await session.commit()

    try:
        chunks = await _load_chunks(session, notebook_id)
        sections = build_sections(chunks)
        if not sections:
            raise PresentationGenerationError("no_content", "Notebook has no ready documents to present.")

        body_slides = await _generate_slides(client, sections, options)
        if not body_slides:
            raise PresentationGenerationError("invalid_llm_response", "No valid slides were generated.")

        slides = [_title_slide(notebook.name)] + body_slides
        result = PresentationGenerationResult(slides=slides)

        if await session.get(Notebook, notebook_id) is None:
            return  # deleted while the LLM call(s) were running; nothing to persist

        output_path = settings.presentations_dir / f"{presentation.id}.pptx"
        render_presentation(result, output_path, notebook.name)

        await _mark_ready(session, notebook_id, options, len(slides), output_path)
    except PresentationGenerationError as exc:
        await _mark_failed(session, notebook_id, exc.reason, exc.detail)
    except LLMUnreachableError as exc:
        await _mark_failed(session, notebook_id, "llm_unreachable", str(exc))
    except LLMTimeoutError as exc:
        await _mark_failed(session, notebook_id, "llm_timeout", str(exc))


def _title_slide(notebook_name: str) -> SlideResult:
    return SlideResult(layout=SlideLayout.TITLE, title=notebook_name, subtitle="Generated from your material")


def _is_renderable_slide(slide: SlideResult) -> bool:
    """The prompt instructs the model on each layout's required fields, but a
    smaller/faster model doesn't always comply — belt and suspenders, same
    reasoning as quiz_generation's duplicate-option filter: a structurally
    incomplete slide (e.g. a two-column layout with only one column) is
    dropped rather than rendered half-blank. Quote and title layouts always
    have a safe fallback (the renderer falls back to the slide's title), so
    they're never dropped here."""
    if slide.layout in (SlideLayout.TWO_COLUMN, SlideLayout.COMPARISON):
        return len(slide.columns) == 2
    if slide.layout == SlideLayout.BULLETS:
        return len(slide.lines) > 0
    return True


async def _generate_slides(
    client: LLMClient, sections: list[str], options: PresentationGenerateRequest
) -> list[SlideResult]:
    target = options.slide_count - 1  # the title slide is added separately, not counted here
    style_clause = _style_clause(options.style)
    focus_clause = _focus_clause(options.focus)

    if len(sections) == 1:
        prompt = PRESENTATION_PROMPT_TEMPLATE.format(
            count=target, style_clause=style_clause, focus_clause=focus_clause, text=sections[0]
        )
        result = await _call_with_retry(client, prompt, PresentationGenerationResult)
        return [s for s in result.slides if _is_renderable_slide(s)][:target]

    per_section = max(1, -(-target // len(sections)))
    all_slides: list[SlideResult] = []
    for section in sections:
        prompt = PRESENTATION_PROMPT_TEMPLATE.format(
            count=per_section, style_clause=style_clause, focus_clause=focus_clause, text=section
        )
        result = await _call_with_retry(client, prompt, PresentationGenerationResult)
        all_slides.extend(s for s in result.slides if _is_renderable_slide(s))
    return all_slides[:target]


async def _call_with_retry[T: BaseModel](client: LLMClient, prompt: str, schema: type[T]) -> T:
    last_detail = ""
    for _ in range(MAX_RETRIES):
        raw = await client.generate_json(prompt)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_detail = str(exc)
    raise PresentationGenerationError("invalid_llm_response", last_detail)


async def _get_or_create_presentation(session: AsyncSession, notebook_id: str) -> Presentation | None:
    existing = await _get_presentation(session, notebook_id)
    if existing is not None:
        return existing

    presentation = Presentation(notebook_id=notebook_id, status=PresentationStatus.PENDING)
    session.add(presentation)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent create for the same notebook
        # (notebook_id is unique) — use the row the other call created.
        await session.rollback()
        return await _get_presentation(session, notebook_id)
    await session.refresh(presentation)
    return presentation


async def _load_chunks(session: AsyncSession, notebook_id: str) -> list[Chunk]:
    result = await session.execute(
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def _mark_ready(
    session: AsyncSession,
    notebook_id: str,
    options: PresentationGenerateRequest,
    slide_count: int,
    output_path: Path,
) -> None:
    presentation = await _get_presentation(session, notebook_id)
    if presentation is None:
        return
    presentation.status = PresentationStatus.READY
    presentation.slide_count = slide_count
    presentation.style = options.style.value
    presentation.focus = options.focus
    presentation.file_path = str(output_path)
    presentation.error_reason = None
    presentation.error_detail = None
    await session.commit()


async def _mark_failed(session: AsyncSession, notebook_id: str, reason: str, detail: str) -> None:
    await session.rollback()
    presentation = await _get_presentation(session, notebook_id)
    if presentation is None:
        return
    presentation.status = PresentationStatus.FAILED
    presentation.error_reason = reason
    presentation.error_detail = detail or None
    await session.commit()


async def _get_presentation(session: AsyncSession, notebook_id: str) -> Presentation | None:
    result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
    return result.scalar_one_or_none()

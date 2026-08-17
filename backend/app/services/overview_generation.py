import asyncio
import json
import re

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import OverviewGenerationError
from app.models import Chunk, Document, DocumentStatus, Notebook, Overview, OverviewStatus
from app.schemas import OverviewResult, SectionSummary, TitleSuggestion
from app.services.ollama_client import OllamaClient, OllamaTimeoutError, OllamaUnreachableError

MAX_RETRIES = 2

UNTITLED_NAME_PATTERN = re.compile(r"^Untitled(?: \d+)?$")

SECTION_PROMPT_TEMPLATE = (
    "Summarize the key topics and concepts covered in this excerpt from a study "
    "document. Respond with ONLY a JSON object matching this exact shape: "
    '{{"summary": "2-4 sentences covering the main topics and concepts in this excerpt"}}.\n\n'
    "Excerpt:\n{text}"
)

SYNTHESIS_PROMPT_TEMPLATE = (
    "You are producing an overview of a study notebook for a student who has "
    "not read its material yet. The material may come from multiple "
    "documents on the same subject; treat it as one combined body of study "
    "material, not separate summaries per document. Respond with ONLY a JSON "
    'object matching this exact shape: {{"short_summary": "string", '
    '"topics": [{{"title": "string", "summary": "one sentence", '
    '"key_concepts": ["string", "string"]}}], "estimated_minutes": integer}}.\n\n'
    "short_summary must be 2-3 plain sentences of flowing prose, not a list "
    "or bullet points or topic titles, describing what this material covers "
    'the way you would explain it out loud to someone who has not seen it '
    '(for example: "This covers the fundamentals of X, including Y and Z, '
    'with an emphasis on W.")\n\n'
    "topics should still identify the distinct topics the material covers, "
    "for a more detailed breakdown a student can open separately.\n\n"
    "estimated_minutes should be a rough estimate of how long a student would "
    "need to study this material, based on how many topics there are and how "
    "dense they are.\n\n"
    "Material:\n{text}"
)

TITLE_PROMPT_TEMPLATE = (
    "Based on these study topics, suggest a short, specific title (2-6 words) "
    "for a study notebook covering this material — like a course or subject "
    'name a student would recognize (e.g. "Machine Learning Basics", "Organic '
    'Chemistry"). Respond with ONLY a JSON object matching this exact shape: '
    '{{"title": "string"}}.\n\n'
    "Topics:\n{topics}"
)

# Serializes every overview-affecting operation (generation, or clearing a
# stale overview) per notebook, keyed by notebook_id. Without this, two
# documents in the same notebook finishing processing close together each
# trigger their own generate_overview call with independent DB sessions;
# without serialization both read/synthesize/write concurrently and the one
# that happens to commit last silently wins — even if it saw a smaller set of
# ready documents than the other. Holding this lock for the full duration of
# each operation (not just the row-creation step) ensures they instead run
# fully one after another, so the final state always reflects a single
# consistent read of the notebook's documents. In-process only (no cross-
# process locking) — proportionate for a single-worker, self-hosted app with
# no task queue (see the "no Celery/Redis" stack decision).
_notebook_locks: dict[str, asyncio.Lock] = {}


def _lock_for(notebook_id: str) -> asyncio.Lock:
    lock = _notebook_locks.get(notebook_id)
    if lock is None:
        lock = asyncio.Lock()
        _notebook_locks[notebook_id] = lock
    return lock


async def generate_overview(
    notebook_id: str,
    session: AsyncSession,
    client: OllamaClient | None = None,
) -> None:
    """Runs section-building -> (map ->) synthesize for one notebook, combining
    every ready document it contains into a single overview, always resolving
    its Overview row to READY or FAILED. Never touches Document.status and
    never raises — the overview is supplementary, not a gate on a document's
    usability, and this is called from inside process_document's own
    try/except, so any exception escaping here would be mistaken for a
    document-processing failure and incorrectly revert an already-successfully-
    processed document back to FAILED."""
    async with _lock_for(notebook_id):
        try:
            await _generate_overview_body(notebook_id, session, client or OllamaClient())
        except Exception as exc:
            try:
                await _mark_failed(session, notebook_id, "generation_error", str(exc))
            except Exception:
                # The session itself is in a state _mark_failed couldn't recover
                # from (e.g. mid-transaction after an unexpected DB error). There
                # is nothing further we can safely do without risking exactly the
                # exception propagation this function exists to prevent.
                pass


async def maybe_regenerate_notebook_overview(notebook_id: str, session: AsyncSession) -> None:
    """Called after a document is removed from a notebook (deleted, or failed
    processing): if the notebook still has other ready documents, its combined
    overview no longer reflects reality and must be regenerated; if none
    remain, the stale overview is removed outright rather than left describing
    content that's gone. The "no ready documents left" branch takes the same
    per-notebook lock generate_overview does, so it can't race a concurrent
    generation for this notebook (e.g. delete the Overview row just before an
    in-flight generate_overview call resurrects it with stale content)."""
    has_ready = await session.execute(
        select(Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .limit(1)
    )
    if has_ready.scalar_one_or_none() is not None:
        await generate_overview(notebook_id, session)
    else:
        async with _lock_for(notebook_id):
            await session.execute(sa_delete(Overview).where(Overview.notebook_id == notebook_id))
            await session.commit()


async def _generate_overview_body(
    notebook_id: str, session: AsyncSession, client: OllamaClient
) -> None:
    if await session.get(Notebook, notebook_id) is None:
        return

    overview = await _get_or_create_overview(session, notebook_id)
    if overview is None:
        return  # lost a race and the notebook/overview no longer resolves cleanly

    # Re-check after the (possibly retried) create — the notebook could have
    # been deleted in the window above.
    if await session.get(Notebook, notebook_id) is None:
        return

    overview.status = OverviewStatus.GENERATING
    await session.commit()

    try:
        chunks = await _load_chunks(session, notebook_id)
        sections = _build_sections(chunks)
        if not sections:
            raise OverviewGenerationError(
                "no_content", "Notebook has no ready documents to summarize."
            )

        result = await _generate_overview_content(client, sections)

        if await session.get(Notebook, notebook_id) is None:
            return  # deleted while the LLM call(s) were running; nothing to persist

        await _mark_ready(session, notebook_id, result, client)
    except OverviewGenerationError as exc:
        await _mark_failed(session, notebook_id, exc.reason, exc.detail)
    except OllamaUnreachableError as exc:
        await _mark_failed(session, notebook_id, "ollama_unreachable", str(exc))
    except OllamaTimeoutError as exc:
        await _mark_failed(session, notebook_id, "ollama_timeout", str(exc))


def _build_sections(chunks: list[Chunk]) -> list[str]:
    """Splits chunk text into contiguous sections covering the whole notebook.
    Small notebooks get a single section (one LLM call). Larger ones are split
    so each section stays under `overview_max_section_chars` (keeping every
    call well within the model's context budget), while the total section
    count is capped at `overview_max_sections` so a huge notebook still costs
    a bounded number of LLM calls — the cap is only exceeded (by letting the
    final section grow) for material so large that even the max section count
    can't otherwise keep every section under the char cap, trading a single
    oversized final section for never silently dropping content."""
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


async def _generate_overview_content(client: OllamaClient, sections: list[str]) -> OverviewResult:
    if len(sections) == 1:
        synthesis_input = sections[0]
    else:
        summaries = [await _summarize_section(client, section) for section in sections]
        synthesis_input = "\n\n".join(
            f"Section {i + 1}: {summary}" for i, summary in enumerate(summaries)
        )
    return await _synthesize_overview(client, synthesis_input)


async def _summarize_section(client: OllamaClient, section_text: str) -> str:
    prompt = SECTION_PROMPT_TEMPLATE.format(text=section_text)
    parsed = await _call_with_retry(client, prompt, SectionSummary)
    return parsed.summary


async def _synthesize_overview(client: OllamaClient, material_text: str) -> OverviewResult:
    prompt = SYNTHESIS_PROMPT_TEMPLATE.format(text=material_text)
    return await _call_with_retry(client, prompt, OverviewResult)


async def _call_with_retry[T: BaseModel](client: OllamaClient, prompt: str, schema: type[T]) -> T:
    last_detail = ""
    for _ in range(MAX_RETRIES):
        raw = await client.generate_json(prompt)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_detail = str(exc)
    raise OverviewGenerationError("invalid_llm_response", last_detail)


async def _maybe_autoname_notebook(
    session: AsyncSession, notebook_id: str, result: OverviewResult, client: OllamaClient
) -> None:
    """Best-effort: renames the notebook from its auto-generated default
    ("Untitled" / "Untitled N") to something content-derived, so users don't
    have to name it themselves before uploading. Never touches a notebook the
    user has already renamed (its name would no longer match the default
    pattern), and never lets a failure here affect the overview it's attached
    to — this is called from inside the same safety net as the rest of
    generation. Uses the same retry-then-give-up helper as the rest of
    generation (not a single unretried attempt) — a small local model
    occasionally returns malformed JSON on the first try, and without a
    retry that silently left a notebook named "Untitled" forever with no
    way to tell why."""
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None or not UNTITLED_NAME_PATTERN.match(notebook.name):
        return
    topics_text = "\n".join(f"- {t.title}: {t.summary}" for t in result.topics[:8])
    prompt = TITLE_PROMPT_TEMPLATE.format(topics=topics_text)
    try:
        suggestion = await _call_with_retry(client, prompt, TitleSuggestion)
        title = suggestion.title.strip()
        if title:
            notebook.name = title[:255]
    except Exception:
        pass


async def _get_or_create_overview(session: AsyncSession, notebook_id: str) -> Overview | None:
    existing = await _get_overview(session, notebook_id)
    if existing is not None:
        return existing

    overview = Overview(notebook_id=notebook_id, status=OverviewStatus.PENDING)
    session.add(overview)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent generate_overview call for the same
        # notebook (e.g. two documents finishing processing at almost the
        # same time) — the other call already created the row (notebook_id is
        # unique), so use that one instead of failing.
        await session.rollback()
        return await _get_overview(session, notebook_id)
    await session.refresh(overview)
    return overview


async def _load_chunks(session: AsyncSession, notebook_id: str) -> list[Chunk]:
    result = await session.execute(
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.notebook_id == notebook_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def _mark_ready(
    session: AsyncSession, notebook_id: str, result: OverviewResult, client: OllamaClient
) -> None:
    overview = await _get_overview(session, notebook_id)
    if overview is None:
        return
    overview.status = OverviewStatus.READY
    overview.short_summary = result.short_summary
    overview.topics_json = json.dumps([topic.model_dump() for topic in result.topics])
    overview.estimated_minutes = result.estimated_minutes
    overview.error_reason = None
    overview.error_detail = None
    await _maybe_autoname_notebook(session, notebook_id, result, client)
    await session.commit()


async def _mark_failed(session: AsyncSession, notebook_id: str, reason: str, detail: str) -> None:
    await session.rollback()
    overview = await _get_overview(session, notebook_id)
    if overview is None:
        return
    overview.status = OverviewStatus.FAILED
    overview.error_reason = reason
    overview.error_detail = detail or None
    await session.commit()


async def _get_overview(session: AsyncSession, notebook_id: str) -> Overview | None:
    result = await session.execute(select(Overview).where(Overview.notebook_id == notebook_id))
    return result.scalar_one_or_none()

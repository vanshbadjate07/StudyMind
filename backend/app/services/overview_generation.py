import json

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import OverviewGenerationError
from app.models import Chunk, Document, Overview, OverviewStatus
from app.schemas import OverviewResult, SectionSummary
from app.services.ollama_client import OllamaClient, OllamaTimeoutError, OllamaUnreachableError

MAX_RETRIES = 2

SECTION_PROMPT_TEMPLATE = (
    "Summarize the key topics and concepts covered in this excerpt from a study "
    "document. Respond with ONLY a JSON object matching this exact shape: "
    '{{"summary": "2-4 sentences covering the main topics and concepts in this excerpt"}}.\n\n'
    "Excerpt:\n{text}"
)

SYNTHESIS_PROMPT_TEMPLATE = (
    "You are producing a structured overview of a study document for a student "
    "who hasn't read it yet. Based on the material below, identify the distinct "
    "topics it covers. Respond with ONLY a JSON object matching this exact shape: "
    '{{"topics": [{{"title": "string", "summary": "one sentence", '
    '"key_concepts": ["string", "string"]}}], "estimated_minutes": integer}}. '
    "estimated_minutes should be a rough estimate of how long a student would "
    "need to study this material, based on how many topics there are and how "
    "dense they are.\n\n"
    "Material:\n{text}"
)


async def generate_overview(
    document_id: str,
    session: AsyncSession,
    client: OllamaClient | None = None,
) -> None:
    """Runs section-building -> (map ->) synthesize for one document, always
    resolving its Overview row to READY or FAILED. Never touches
    Document.status and never raises — the overview is supplementary, not a
    gate on the document's usability, and this is called from inside
    process_document's own try/except, so any exception escaping here would
    be mistaken for a document-processing failure and incorrectly revert an
    already-successfully-processed document back to FAILED."""
    try:
        await _generate_overview_body(document_id, session, client or OllamaClient())
    except Exception as exc:
        try:
            await _mark_failed(session, document_id, "generation_error", str(exc))
        except Exception:
            # The session itself is in a state _mark_failed couldn't recover
            # from (e.g. mid-transaction after an unexpected DB error). There
            # is nothing further we can safely do without risking exactly the
            # exception propagation this function exists to prevent.
            pass


async def _generate_overview_body(
    document_id: str, session: AsyncSession, client: OllamaClient
) -> None:
    if await session.get(Document, document_id) is None:
        return

    overview = await _get_or_create_overview(session, document_id)
    if overview is None:
        return  # lost a race and the document/overview no longer resolves cleanly

    # Re-check after the (possibly retried) create — the document could have
    # been deleted in the window above.
    if await session.get(Document, document_id) is None:
        return

    overview.status = OverviewStatus.GENERATING
    await session.commit()

    try:
        chunks = await _load_chunks(session, document_id)
        sections = _build_sections(chunks)
        if not sections:
            raise OverviewGenerationError("no_content", "Document has no chunks to summarize.")

        result = await _generate_overview_content(client, sections)

        if await session.get(Document, document_id) is None:
            return  # deleted while the LLM call(s) were running; nothing to persist

        await _mark_ready(session, document_id, result)
    except OverviewGenerationError as exc:
        await _mark_failed(session, document_id, exc.reason, exc.detail)
    except OllamaUnreachableError as exc:
        await _mark_failed(session, document_id, "ollama_unreachable", str(exc))
    except OllamaTimeoutError as exc:
        await _mark_failed(session, document_id, "ollama_timeout", str(exc))


def _build_sections(chunks: list[Chunk]) -> list[str]:
    """Splits chunk text into contiguous sections covering the whole document.
    Small documents get a single section (one LLM call). Larger documents are
    split so each section stays under `overview_max_section_chars` (keeping
    every call well within the model's context budget), while the total
    section count is capped at `overview_max_sections` so a huge document
    still costs a bounded number of LLM calls — the cap is only exceeded (by
    letting the final section grow) for documents so large that even the max
    section count can't otherwise keep every section under the char cap,
    trading a single oversized final section for never silently dropping
    content."""
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


async def _get_or_create_overview(session: AsyncSession, document_id: str) -> Overview | None:
    existing = await _get_overview(session, document_id)
    if existing is not None:
        return existing

    overview = Overview(document_id=document_id, status=OverviewStatus.PENDING)
    session.add(overview)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent generate_overview call for the same
        # document (the auto-triggered run and a manual /regenerate can land
        # at almost the same time) — the other call already created the row
        # (document_id is unique), so use that one instead of failing.
        await session.rollback()
        return await _get_overview(session, document_id)
    await session.refresh(overview)
    return overview


async def _load_chunks(session: AsyncSession, document_id: str) -> list[Chunk]:
    result = await session.execute(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def _mark_ready(session: AsyncSession, document_id: str, result: OverviewResult) -> None:
    overview = await _get_overview(session, document_id)
    if overview is None:
        return
    overview.status = OverviewStatus.READY
    overview.topics_json = json.dumps([topic.model_dump() for topic in result.topics])
    overview.estimated_minutes = result.estimated_minutes
    overview.error_reason = None
    overview.error_detail = None
    await session.commit()


async def _mark_failed(session: AsyncSession, document_id: str, reason: str, detail: str) -> None:
    await session.rollback()
    overview = await _get_overview(session, document_id)
    if overview is None:
        return
    overview.status = OverviewStatus.FAILED
    overview.error_reason = reason
    overview.error_detail = detail or None
    await session.commit()


async def _get_overview(session: AsyncSession, document_id: str) -> Overview | None:
    result = await session.execute(select(Overview).where(Overview.document_id == document_id))
    return result.scalar_one_or_none()

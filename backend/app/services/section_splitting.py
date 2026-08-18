from app.config import settings
from app.models import Chunk


def build_sections(chunks: list[Chunk]) -> list[str]:
    """Splits chunk text into contiguous sections covering the whole notebook.
    Small notebooks get a single section (one LLM call). Larger ones are split
    so each section stays under `overview_max_section_chars` (keeping every
    call well within the model's context budget), while the total section
    count is capped at `overview_max_sections` so a huge notebook still costs
    a bounded number of LLM calls — the cap is only exceeded (by letting the
    final section grow) for material so large that even the max section count
    can't otherwise keep every section under the char cap, trading a single
    oversized final section for never silently dropping content.

    Shared by overview, quiz, and presentation generation — all three split
    a notebook's chunks into LLM-sized sections the same way, reusing
    overview's sizing settings rather than each maintaining its own copy."""
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

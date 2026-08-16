import re
from dataclasses import dataclass

from app.config import settings

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class TextChunk:
    text: str
    page_number: int | None


def chunk_text(
    text: str,
    page_number: int | None = None,
    chunk_size: int = settings.chunk_size_chars,
    overlap: int = settings.chunk_overlap_chars,
) -> list[TextChunk]:
    """Splits text into overlapping chunks, preferring paragraph then sentence
    boundaries over hard character cuts, so retrieval doesn't see sentences sliced
    in half."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [TextChunk(text=text, page_number=page_number)]

    units = _split_into_units(text, chunk_size)

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}".strip() if current else unit
        if len(candidate) <= chunk_size or not current:
            current = candidate
        else:
            chunks.append(current)
            overlap_text = current[-overlap:] if overlap > 0 else ""
            current = f"{overlap_text} {unit}".strip()
    if current:
        chunks.append(current)

    return [TextChunk(text=c, page_number=page_number) for c in chunks if c.strip()]


def _split_into_units(text: str, chunk_size: int) -> list[str]:
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
            continue
        units.extend(_split_long_paragraph(paragraph, chunk_size))
    return units


def _split_long_paragraph(paragraph: str, chunk_size: int) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(paragraph) if s.strip()]
    units: list[str] = []
    for sentence in sentences:
        if len(sentence) <= chunk_size:
            units.append(sentence)
        else:
            units.extend(sentence[i : i + chunk_size] for i in range(0, len(sentence), chunk_size))
    return units

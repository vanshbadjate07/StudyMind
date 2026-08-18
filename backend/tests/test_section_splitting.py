from app.models import Chunk
from app.services.section_splitting import build_sections


def _chunk(text: str, index: int) -> Chunk:
    return Chunk(id=f"chunk-{index}", document_id="doc-1", chunk_index=index, text=text, page_number=1)


class TestBuildSections:
    """Shared by overview, quiz, and presentation generation — tested once
    here instead of once per feature, since it's the same function."""

    def test_small_document_returns_a_single_section(self) -> None:
        chunks = [_chunk("A short chunk of text.", 0)]
        sections = build_sections(chunks)
        assert len(sections) == 1
        assert sections[0] == "A short chunk of text."

    def test_large_document_splits_into_bounded_sections(self) -> None:
        # ~40,000 chars total, well over the single-pass budget and the target
        # per-section size, so this should hit the max-section cap, not one
        # section per chunk.
        chunks = [_chunk("word " * 200, i) for i in range(40)]
        sections = build_sections(chunks)
        assert 1 < len(sections) <= 8

    def test_sections_together_cover_the_whole_document(self) -> None:
        chunks = [_chunk(f"unique-marker-{i} " * 100, i) for i in range(20)]
        sections = build_sections(chunks)
        combined = "\n\n".join(sections)
        for i in range(20):
            assert f"unique-marker-{i}" in combined

    def test_empty_chunk_list_returns_no_sections(self) -> None:
        assert build_sections([]) == []

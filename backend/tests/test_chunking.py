from app.services.chunking import chunk_text


def test_short_text_returns_single_chunk() -> None:
    chunks = chunk_text("A short sentence about photosynthesis.", chunk_size=1000, overlap=150)

    assert len(chunks) == 1
    assert chunks[0].text == "A short sentence about photosynthesis."


def test_text_with_no_paragraph_breaks_still_splits() -> None:
    sentence = "The mitochondria is the powerhouse of the cell. "
    text = sentence * 40  # no blank lines anywhere, forces sentence-level fallback

    chunks = chunk_text(text, chunk_size=200, overlap=30)

    assert len(chunks) > 1
    assert all(len(c.text) <= 260 for c in chunks)  # allow small overlap slack


def test_unicode_text_does_not_break_mid_character() -> None:
    paragraph = "Photosynthèse (français) et 光合作用 (中文) sont liés à la vie. " * 30
    chunks = chunk_text(paragraph, chunk_size=150, overlap=20)

    assert len(chunks) > 1
    for c in chunks:
        # Would raise UnicodeDecodeError if any chunk contained a broken surrogate/byte
        c.text.encode("utf-8").decode("utf-8")


def test_consecutive_chunks_share_overlap_content() -> None:
    paragraphs = "\n\n".join(f"Paragraph {i} discusses topic number {i} in detail." for i in range(30))

    chunks = chunk_text(paragraphs, chunk_size=200, overlap=50)

    assert len(chunks) > 1
    tail_of_first = chunks[0].text[-30:]
    assert tail_of_first.strip() in chunks[1].text


def test_page_number_is_preserved_on_every_chunk() -> None:
    chunks = chunk_text("Some content. " * 100, page_number=7, chunk_size=100, overlap=10)

    assert len(chunks) > 1
    assert all(c.page_number == 7 for c in chunks)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == []

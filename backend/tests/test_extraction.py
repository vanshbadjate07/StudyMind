from pathlib import Path

import pytest

from app.errors import UnsupportedDocumentError
from app.services.extraction import extract_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_normal_pdf_extracts_text_from_every_page() -> None:
    doc = extract_text(FIXTURES / "normal.pdf")

    assert doc.page_count == 3
    assert doc.char_count > 0
    assert "machine learning" in doc.full_text.lower()
    assert "neural network" in doc.full_text.lower()


def test_single_page_pdf_extracts() -> None:
    doc = extract_text(FIXTURES / "single_page.pdf")

    assert doc.page_count == 1
    assert "water cycle" in doc.full_text.lower()


def test_zero_page_pdf_raises_empty_document() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "empty.pdf")

    assert exc_info.value.reason == "empty_document"


def test_blank_page_pdf_raises_no_extractable_text() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "blank_page.pdf")

    assert exc_info.value.reason == "no_extractable_text"


def test_corrupted_pdf_raises_invalid_pdf() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "corrupted.pdf")

    assert exc_info.value.reason == "invalid_pdf"


def test_password_protected_pdf_raises_password_protected() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "password.pdf")

    assert exc_info.value.reason == "password_protected"


def test_scanned_image_only_pdf_raises_scanned_or_image_only() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "scanned.pdf")

    assert exc_info.value.reason == "scanned_or_image_only"


def test_non_pdf_file_raises_invalid_pdf() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "not_a_pdf.pdf")

    assert exc_info.value.reason == "invalid_pdf"


def test_missing_file_raises_invalid_pdf() -> None:
    with pytest.raises(UnsupportedDocumentError) as exc_info:
        extract_text(FIXTURES / "does_not_exist.pdf")

    assert exc_info.value.reason == "invalid_pdf"

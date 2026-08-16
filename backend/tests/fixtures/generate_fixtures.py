"""Regenerates the binary PDF fixtures used by extraction/pipeline tests.

Run manually when fixtures need to change: python tests/fixtures/generate_fixtures.py
"""

from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

FIXTURES_DIR = Path(__file__).parent
BODY_RECT = fitz.Rect(72, 72, 523, 770)  # 1-inch margins on a standard 595x842 page


def _insert_wrapped(page: fitz.Page, text: str) -> None:
    # insert_text draws a single line with no word-wrap and silently clips
    # anything past the page edge — insert_textbox wraps within BODY_RECT like
    # a real document, which is what these fixtures need to represent.
    remaining = page.insert_textbox(BODY_RECT, text, fontsize=11)
    if remaining < 0:
        raise ValueError("fixture text overflowed the page body rect — shorten it")


def make_normal_pdf() -> None:
    doc = fitz.open()
    topics = [
        "Chapter 1: Introduction to Machine Learning\n\n"
        "Machine learning is a subfield of artificial intelligence that focuses on building systems "
        "that learn from data. Supervised learning uses labeled examples, while unsupervised learning "
        "finds patterns in unlabeled data.",
        "Chapter 2: Neural Networks\n\n"
        "A neural network consists of layers of interconnected nodes. Each connection has a weight "
        "that is adjusted during training via backpropagation. Deep learning refers to networks with "
        "many hidden layers.",
        "Chapter 3: Evaluation Metrics\n\n"
        "Accuracy, precision, recall, and F1 score are common metrics for classification tasks. "
        "Choosing the right metric depends on the cost of false positives versus false negatives.",
    ]
    for text in topics:
        page = doc.new_page()
        _insert_wrapped(page, text)
    doc.save(FIXTURES_DIR / "normal.pdf")
    doc.close()


def make_single_page_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page()
    _insert_wrapped(
        page,
        "A single page document about the water cycle: evaporation, condensation, "
        "precipitation, and collection form a continuous loop.",
    )
    doc.save(FIXTURES_DIR / "single_page.pdf")
    doc.close()


def make_empty_pdf() -> None:
    # PyMuPDF refuses to *save* a zero-page document, but a hand-written minimal
    # PDF with an empty page tree is valid and MuPDF opens it fine (page_count == 0).
    # That's exactly the case we need to exercise: a structurally valid PDF with no pages.
    raw = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\n"
        b"%%EOF\n"
    )
    (FIXTURES_DIR / "empty.pdf").write_bytes(raw)


def make_blank_page_pdf() -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(FIXTURES_DIR / "blank_page.pdf")
    doc.close()


def make_corrupted_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page()
    _insert_wrapped(page, "This will be truncated into garbage.")
    data = doc.tobytes()
    doc.close()
    # Truncating mid-header (before any object/xref) reliably makes MuPDF fail to open
    # the stream at all. A larger truncation can leave enough structure for MuPDF's
    # repair pass to recover an openable-but-empty document, which isn't what this
    # fixture is meant to test.
    (FIXTURES_DIR / "corrupted.pdf").write_bytes(data[:20])


def make_password_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page()
    _insert_wrapped(page, "Secret protected content.")
    doc.save(
        FIXTURES_DIR / "password.pdf",
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()


def make_scanned_pdf() -> None:
    # Small, low-detail image is enough to exercise "has an image, no text layer" —
    # no need for a realistic scan, just a valid embeddable image to keep the fixture small.
    image_path = FIXTURES_DIR / "_scanned_page.jpg"
    Image.new("L", (200, 260), color=200).save(image_path, format="JPEG", quality=40)

    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(FIXTURES_DIR / "scanned.pdf")
    doc.close()
    image_path.unlink()


def make_not_a_pdf() -> None:
    (FIXTURES_DIR / "not_a_pdf.pdf").write_text("This is actually a plain text file, not a PDF.")


if __name__ == "__main__":
    make_normal_pdf()
    make_single_page_pdf()
    make_empty_pdf()
    make_blank_page_pdf()
    make_corrupted_pdf()
    make_password_pdf()
    make_scanned_pdf()
    make_not_a_pdf()
    print("Fixtures generated in", FIXTURES_DIR)

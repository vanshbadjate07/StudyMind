"""Regenerates the binary PDF fixtures used by extraction/pipeline tests.

Run manually when fixtures need to change: python tests/fixtures/generate_fixtures.py
"""

from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from PIL import Image
from pptx import Presentation

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


def make_normal_docx() -> None:
    doc = DocxDocument()
    doc.add_paragraph("Chapter 1: Introduction to Machine Learning")
    doc.add_paragraph(
        "Machine learning is a subfield of artificial intelligence that focuses on building "
        "systems that learn from data."
    )
    doc.add_paragraph("Chapter 2: Neural Networks")
    doc.add_paragraph(
        "A neural network consists of layers of interconnected nodes updated during training "
        "via backpropagation."
    )
    doc.save(FIXTURES_DIR / "normal.docx")


def make_empty_docx() -> None:
    DocxDocument().save(FIXTURES_DIR / "empty.docx")


def make_corrupted_docx() -> None:
    # Must still start with the ZIP magic bytes (PK\x03\x04) to clear the
    # upload route's signature check — the point of this fixture is to fail
    # later, at python-docx's parse step, not at upload time.
    doc = DocxDocument()
    doc.add_paragraph("This will be truncated into garbage.")
    buffer = FIXTURES_DIR / "_tmp_corrupted.docx"
    doc.save(buffer)
    data = buffer.read_bytes()
    buffer.unlink()
    (FIXTURES_DIR / "corrupted.docx").write_bytes(data[:20])


def make_normal_pptx() -> None:
    presentation = Presentation()
    title_layout = presentation.slide_layouts[0]
    slide1 = presentation.slides.add_slide(title_layout)
    slide1.shapes.title.text = "Introduction to Machine Learning"
    slide1.placeholders[1].text = "Supervised vs. unsupervised learning"

    slide2 = presentation.slides.add_slide(title_layout)
    slide2.shapes.title.text = "Neural Networks"
    slide2.placeholders[1].text = "Layers, weights, and backpropagation"

    presentation.save(FIXTURES_DIR / "normal.pptx")


def make_empty_pptx() -> None:
    Presentation().save(FIXTURES_DIR / "empty.pptx")


def make_corrupted_pptx() -> None:
    # Same reasoning as make_corrupted_docx: must still start with the ZIP
    # magic bytes to clear the upload route's signature check.
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[0])
    buffer = FIXTURES_DIR / "_tmp_corrupted.pptx"
    presentation.save(buffer)
    data = buffer.read_bytes()
    buffer.unlink()
    (FIXTURES_DIR / "corrupted.pptx").write_bytes(data[:20])


def make_normal_txt() -> None:
    (FIXTURES_DIR / "normal.txt").write_text(
        "Machine learning is a subfield of artificial intelligence focused on building systems "
        "that learn from data.\n\nSupervised learning uses labeled examples."
    )


def make_empty_txt() -> None:
    (FIXTURES_DIR / "empty.txt").write_text("   \n\n  ")


def make_binary_txt() -> None:
    (FIXTURES_DIR / "binary.txt").write_bytes(bytes(range(0, 256)))


def make_normal_md() -> None:
    (FIXTURES_DIR / "normal.md").write_text(
        "# Study Notes\n\n## Machine Learning\n\nSupervised learning uses labeled examples."
    )


if __name__ == "__main__":
    make_normal_pdf()
    make_single_page_pdf()
    make_empty_pdf()
    make_blank_page_pdf()
    make_corrupted_pdf()
    make_password_pdf()
    make_scanned_pdf()
    make_not_a_pdf()
    make_normal_docx()
    make_empty_docx()
    make_corrupted_docx()
    make_normal_pptx()
    make_empty_pptx()
    make_corrupted_pptx()
    make_normal_txt()
    make_empty_txt()
    make_binary_txt()
    make_normal_md()
    print("Fixtures generated in", FIXTURES_DIR)

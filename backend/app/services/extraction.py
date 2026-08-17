from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from pptx import Presentation

from app.errors import UnsupportedDocumentError


@dataclass(frozen=True)
class ExtractedPage:
    # None for formats with no real pagination (txt, md, docx) — Word doesn't
    # store page breaks in its XML, they're computed at render/print time, so
    # inventing a page number for docx would be fiction, not data. PDF and
    # pptx (one "page" per slide) have real, meaningful units and always set this.
    page_number: int | None
    text: str
    has_images: bool


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[ExtractedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


def extract_text(path: Path) -> ExtractedDocument:
    """Dispatches on file extension and raises UnsupportedDocumentError with
    a stable `reason` on any failure to extract. Keep in sync with
    app.config.Settings.allowed_extensions, which gates uploads before a
    file ever reaches this function."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        extracted = _extract_pdf(path)
    elif suffix in (".txt", ".md"):
        extracted = _extract_plain_text(path)
    elif suffix == ".docx":
        extracted = _extract_docx(path)
    elif suffix == ".pptx":
        extracted = _extract_pptx(path)
    else:
        raise UnsupportedDocumentError("unsupported_file_type", suffix)

    any_text = any(p.text for p in extracted.pages)
    any_images = any(p.has_images for p in extracted.pages)
    if not any_text:
        if any_images:
            raise UnsupportedDocumentError("scanned_or_image_only")
        raise UnsupportedDocumentError("no_extractable_text")

    return extracted


def _extract_pdf(path: Path) -> ExtractedDocument:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_pdf", str(exc)) from exc

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise UnsupportedDocumentError("password_protected")

        if doc.page_count == 0:
            raise UnsupportedDocumentError("empty_document")

        pages = _extract_pdf_pages(doc)
    except UnsupportedDocumentError:
        raise
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_pdf", str(exc)) from exc
    finally:
        doc.close()

    return ExtractedDocument(pages=pages)


def _extract_pdf_pages(doc: fitz.Document) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text().strip()
        has_images = len(page.get_images(full=True)) > 0
        pages.append(ExtractedPage(page_number=i + 1, text=text, has_images=has_images))
    return pages


def _extract_plain_text(path: Path) -> ExtractedDocument:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UnsupportedDocumentError("invalid_file", str(exc)) from exc

    if not raw.strip():
        raise UnsupportedDocumentError("empty_document")

    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise UnsupportedDocumentError("invalid_file", "Not valid UTF-8 text.") from exc

    return ExtractedDocument(pages=[ExtractedPage(page_number=None, text=text, has_images=False)])


def _extract_docx(path: Path) -> ExtractedDocument:
    try:
        doc = DocxDocument(path)
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_docx", str(exc)) from exc

    text = "\n".join(paragraph.text for paragraph in doc.paragraphs).strip()
    # A docx with zero paragraphs (a truly blank document) is the closest
    # equivalent to a PDF with zero pages — distinct from having paragraphs
    # that are all empty, which is closer to "no_extractable_text".
    if not doc.paragraphs:
        raise UnsupportedDocumentError("empty_document")

    return ExtractedDocument(pages=[ExtractedPage(page_number=None, text=text, has_images=False)])


def _extract_pptx(path: Path) -> ExtractedDocument:
    try:
        presentation = Presentation(str(path))
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_pptx", str(exc)) from exc

    if len(presentation.slides) == 0:
        raise UnsupportedDocumentError("empty_document")

    pages: list[ExtractedPage] = []
    for i, slide in enumerate(presentation.slides):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        has_images = any(shape.shape_type == 13 for shape in slide.shapes)  # MSO_SHAPE_TYPE.PICTURE
        pages.append(
            ExtractedPage(page_number=i + 1, text="\n".join(texts).strip(), has_images=has_images)
        )
    return ExtractedDocument(pages=pages)

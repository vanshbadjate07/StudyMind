from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from app.errors import UnsupportedDocumentError


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
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
    """Raises UnsupportedDocumentError with a stable `reason` on any failure to extract."""
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_pdf", str(exc)) from exc

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise UnsupportedDocumentError("password_protected")

        if doc.page_count == 0:
            raise UnsupportedDocumentError("empty_document")

        pages = _extract_pages(doc)
    except UnsupportedDocumentError:
        raise
    except Exception as exc:
        raise UnsupportedDocumentError("invalid_pdf", str(exc)) from exc
    finally:
        doc.close()

    any_text = any(p.text for p in pages)
    any_images = any(p.has_images for p in pages)
    if not any_text:
        if any_images:
            raise UnsupportedDocumentError("scanned_or_image_only")
        raise UnsupportedDocumentError("no_extractable_text")

    return ExtractedDocument(pages=pages)


def _extract_pages(doc: fitz.Document) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text().strip()
        has_images = len(page.get_images(full=True)) > 0
        pages.append(ExtractedPage(page_number=i + 1, text=text, has_images=has_images))
    return pages

"""PDF text extraction: preserve physical PDF page numbers, including blank pages."""

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

from pypdf import PdfReader

from app.processing.errors import LostLease, PermanentProcessingError as ProcessingError
from app.processing.metadata import metadata_from_reader


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedPDF:
    pages: tuple[PageText, ...]
    page_count: int
    title: str | None = None
    author: str | None = None


def extract_pdf(
    content: bytes, *, max_pages: int = 2000, max_chars: int = 5_000_000,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractedPDF:
    """Read text pages safely; report scanned, empty, protected, or broken PDFs."""
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ProcessingError("This PDF is password-protected. Upload an unlocked copy.")
        page_count = len(reader.pages)
        if not page_count:
            raise ProcessingError("This PDF contains no pages. Upload a book with readable text.")
        if page_count > max_pages:
            raise ProcessingError(f"This PDF has more than {max_pages} pages. Split it into smaller books.")
        pages: list[PageText] = []
        total_chars = 0
        image_pages = 0
        for number, page in enumerate(reader.pages, start=1):
            # Normalize ligatures and whitespace without changing page boundaries.
            text = unicodedata.normalize("NFKC", page.extract_text() or "").replace("\x00", "")
            text = re.sub(r"[^\S\n]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            total_chars += len(text)
            if total_chars > max_chars:
                raise ProcessingError("This PDF contains too much text. Split it into smaller books.")
            if text:
                pages.append(PageText(number, text))
            else:
                resources = page.get("/Resources", {})
                if hasattr(resources, "get_object"):
                    resources = resources.get_object()
                objects = resources.get("/XObject", {})
                if hasattr(objects, "get_object"):
                    objects = objects.get_object()
                image_pages += any(obj.get_object().get("/Subtype") == "/Image" for obj in objects.values())
            if progress and (number % 20 == 0 or number == page_count):
                progress(number, page_count)
        if not pages:
            if image_pages:
                raise ProcessingError("This PDF appears to be scanned. Run OCR first, then upload the text-based PDF.")
            raise ProcessingError("This PDF has no extractable text. It may be empty or need OCR.")
        metadata = metadata_from_reader(reader)
        return ExtractedPDF(tuple(pages), page_count, **metadata)
    except (ProcessingError, LostLease):
        raise
    except Exception as exc:
        raise ProcessingError("This PDF could not be read. It may be damaged or use an unsupported format.") from exc

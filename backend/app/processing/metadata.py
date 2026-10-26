"""Book metadata: use the PDF's stated title/author without guessing from a filename."""

import re
import unicodedata
from io import BytesIO

from pypdf import PdfReader


def clean_metadata(value) -> str | None:
    """Ignore blank/generic values and bound untrusted PDF metadata for display."""
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).replace("\x00", "")).strip()
    if not value or value.lower() in {"untitled", "unknown", "none", "document", "title", "author"}:
        return None
    return value[:300]


def metadata_from_reader(reader: PdfReader) -> dict:
    information = reader.metadata
    return {"title": clean_metadata(information.title if information else None),
        "author": clean_metadata(information.author if information else None)}


def read_pdf_metadata(content: bytes) -> dict:
    """Backfill existing ready books without re-extracting or replacing their chunks."""
    reader = PdfReader(BytesIO(content), strict=False)
    if reader.is_encrypted:
        return {"title": None, "author": None}
    return metadata_from_reader(reader)

"""Text chunking: overlapping passages with the original book's page ranges."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from app.processing.errors import ProcessingError
from app.processing.pdf import PageText


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    page_start: int
    page_end: int


def chunk_pages(
    pages: tuple[PageText, ...], *, chunk_size: int = 1400,
    overlap: int = 200, max_chunks: int = 5000,
) -> list[TextChunk]:
    """Prefer word boundaries; retain overlap and page provenance across pages."""
    if chunk_size < 2 or not 0 <= overlap < chunk_size:
        raise ValueError("Chunk size must be positive and overlap must be smaller")
    texts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    numbers: list[int] = []
    offset = 0
    for page in pages:
        if not page.text.strip():
            continue
        starts.append(offset)
        texts.append(page.text)
        offset += len(page.text)
        ends.append(offset)
        numbers.append(page.page_number)
        offset += 2  # The joining newlines belong to neither adjacent page.
    body = "\n\n".join(texts)
    chunks: list[TextChunk] = []
    start = 0
    while start < len(body):
        end = min(start + chunk_size, len(body))
        if end < len(body):
            boundary = max(body.rfind("\n", start + chunk_size // 2, end), body.rfind(" ", start + chunk_size // 2, end))
            if boundary > start + overlap:
                end = boundary
        raw = body[start:end]
        text = raw.strip()
        if text:
            actual_start = start + len(raw) - len(raw.lstrip())
            actual_end = end - len(raw) + len(raw.rstrip())
            first = bisect_right(ends, actual_start)
            last = bisect_left(starts, actual_end) - 1
            chunks.append(TextChunk(len(chunks), text, numbers[first], numbers[last]))
            if len(chunks) > max_chunks:
                raise ProcessingError("This book needs too many passages. Split it into smaller PDFs.")
        if end == len(body):
            break
        start = max(start + 1, end - overlap)
    return chunks

"""PDF text extraction and text chunking: preserve evidence and reject bad input."""

import pytest

from app.processing.chunking import chunk_pages
from app.processing.errors import ProcessingError
from app.processing.pdf import PageText, extract_pdf
from tests.pdf_factory import make_pdf


def test_physical_page_numbers_include_blank_pages():
    result = extract_pdf(make_pdf(['First page has readable text.', '', 'The third page contains evidence.']))
    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 3]
    assert 'third page' in result.pages[1].text


@pytest.mark.parametrize(('content', 'message'), [
    (make_pdf([]), 'no pages'),
    (make_pdf(['']), 'no extractable text'),
    (make_pdf([''], image_only=True), 'OCR'),
    (make_pdf(['Private text'], encrypted=True), 'password-protected'),
    (b'%PDF-this-is-damaged', 'could not be read'),
])
def test_unusable_pdf_has_actionable_failure(content, message):
    with pytest.raises(ProcessingError, match=message):
        extract_pdf(content)


def test_extraction_resource_limits():
    with pytest.raises(ProcessingError, match='more than 1 pages'):
        extract_pdf(make_pdf(['One', 'Two']), max_pages=1)
    with pytest.raises(ProcessingError, match='too much text'):
        extract_pdf(make_pdf(['A substantial amount of text.']), max_chars=5)


def test_chunk_overlap_covers_all_text_and_correct_page_ranges():
    pages = (PageText(1, 'A' * 90), PageText(3, 'B' * 90), PageText(4, 'C' * 90))
    chunks = chunk_pages(pages, chunk_size=100, overlap=20)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.content) <= 100 for chunk in chunks)
    assert chunks[0].page_start == 1 and chunks[0].page_end == 1
    assert any(chunk.page_start == 1 and chunk.page_end == 3 for chunk in chunks)
    assert chunks[-1].page_end == 4
    shared = max(size for size in range(21) if chunks[0].content.endswith(chunks[1].content[:size]))
    assert shared >= 18  # At most the two joining newlines are stripped.
    # Unique numbered words make dropped text detectable across every boundary.
    source = ' '.join(f'word{i:04}' for i in range(200))
    word_chunks = chunk_pages((PageText(1, source),), chunk_size=160, overlap=30)
    for word in source.split():
        assert any(word in chunk.content for chunk in word_chunks)


def test_chunk_boundaries_do_not_credit_adjacent_blank_pages():
    chunks = chunk_pages((PageText(2, 'hello'), PageText(5, 'world')), chunk_size=5, overlap=0)
    assert (chunks[0].content, chunks[0].page_start, chunks[0].page_end) == ('hello', 2, 2)
    assert ''.join(chunk.content for chunk in chunks[1:]) == 'world'
    assert all(chunk.page_start == chunk.page_end == 5 for chunk in chunks[1:])


def test_chunk_limits_and_settings():
    with pytest.raises(ValueError):
        chunk_pages((PageText(1, 'text'),), chunk_size=20, overlap=20)
    with pytest.raises(ProcessingError, match='too many passages'):
        chunk_pages((PageText(1, 'x' * 100),), chunk_size=20, overlap=0, max_chunks=2)

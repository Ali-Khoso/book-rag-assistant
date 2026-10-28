"""Book overviews: recognize broad requests and sample bounded, cited evidence."""

import re

from app.answers.grounding import content_words


GENERIC_WORDS = set('give me a an the short brief concise quick overall whole entire general high level simple summary summarise summarize summarization summarisation overview synopsis plot story book novel document pdf text what is it this that about in of and tell explain describe please now can you could would some main idea ideas points themes happens happening contents'.split())
ADMINISTRATIVE_TEXT = re.compile(
    r'project gutenberg|all rights reserved|table of contents|transcriber.s note|'
    r'this ebook edition was published|standardebooks\.org/ebooks', re.I)
LOW_INFORMATION = re.compile(r'\bpresiding\b|the following resolutions|oration upon this occasion', re.I)


def overview_intent(question: str) -> bool:
    """Route generic summaries; named topics and chapters still use topic search."""
    words = re.findall(r'[a-z]+|\d+', question.casefold())
    text = ' '.join(words)
    marker = re.search(r'\b(summary|summarize|summarise|overview|synopsis|plot)\b', text)
    marker = marker or re.search(r'\bwhat is (?:this |the |that )?(?:book|novel|story|document|pdf) about\b|\bwhat is the story\b', text)
    # A specific subject cannot use summary wording to bypass answerability.
    return bool(marker and words and not (set(words) - GENERIC_WORDS))


def overview_indices(chunk_count: int) -> list[int]:
    """Fetch at most 17 positions, with opening context and later coverage."""
    if chunk_count < 1:
        return []
    positions = [*range(min(chunk_count, 6))]
    positions.extend(round((chunk_count - 1) * fraction)
        for fraction in (.01, .025, .05, .1, .2, .35, .5, .65, .8, .9, .98))
    return sorted(set(positions))


def source_sentences(text: str) -> list[str]:
    """Keep complete source sentences; avoid splitting common names/initials."""
    text = ' '.join(text.split())
    ends = []
    for match in re.finditer(r'[.!?][\ufffd\'\"\u201d\u2019]*\s+(?=[\ufffd\'\"\u201c\u2018]*[A-Z])', text):
        prefix = text[:match.start() + 1]
        if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Esq|St|Jr|Sr|[A-Z])\.$', prefix):
            continue
        ends.append(match.end())
    if text.rstrip('\ufffd\'\"\u201d\u2019').endswith(('.', '!', '?')):
        ends.append(len(text))
    sentences, start = [], 0
    for end in ends:
        sentence = text[start:end].strip()
        start = end
        if (60 <= len(sentence) <= 600 and len(content_words(sentence)) >= 8
                and not LOW_INFORMATION.search(sentence)
                and not re.match(r'^[\ufffd\'\"\u201c\u2018]*(?:He|She|It|They|His|Her|Their)\b', sentence)):
            first = sentence.lstrip('\ufffd\'\"\u201c\u2018')[:1]
            if first.isupper():
                sentences.append(sentence)
    return sentences


def overview_evidence(rows: list[dict], book: dict, *, limit: int, budget: int) -> list[dict]:
    """Spread verified sentences over the current owned index within the budget."""
    candidates = sorted((row for row in rows
        if row.get('document_id') == book['id']
        and row.get('user_id') == book['user_id']
        and row.get('processing_run_id') == book['processing_run_id']
        and len(content_words(row['content'])) >= 25
        and not ADMINISTRATIVE_TEXT.search(row['content'])), key=lambda row: row['chunk_index'])
    book_words = content_words(book.get('title') or '')
    prepared = []
    for row in candidates:
        sentences = source_sentences(row['content'])
        if sentences:
            sentence = max(sentences, key=lambda value: (
                len(content_words(value) & book_words), -abs(28 - len(content_words(value)))))
            prepared.append({**row, 'content': sentence})
    count = min(len(prepared), max(1, limit), max(1, budget // 600))
    if not count:
        return []
    # Keep enough opening setup to identify people/subject before sampling later
    # developments. Isolated late-book dialogue cannot explain a book's premise.
    opening = min(3, max(1, count // 2))
    indices = list(range(opening))
    remaining = count - opening
    if remaining:
        indices.extend(opening - 1 + round((i + 1) * (len(prepared) - opening) / remaining)
            for i in range(remaining))
    evidence = []
    for index in indices:
        row = prepared[index]
        content = row['content']
        if content:
            evidence.append({**row, 'content': content, 'source_id': f's{len(evidence) + 1}'})
    return evidence


def overview_scope(evidence: list[dict]) -> str:
    return (f"Brief overview based on {len(evidence)} selected passages from this book. "
        "Events or themes in other sections may be missing.")

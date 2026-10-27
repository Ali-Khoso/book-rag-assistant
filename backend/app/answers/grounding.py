"""Citation verification: validate quotes/IDs and derive every source from storage."""

import re
from dataclasses import dataclass

from app.answers.models import ModelAnswer


INSUFFICIENT = "I couldn't find enough evidence in this book to answer that question. Try asking about a specific topic or passage."
STOP_WORDS = set('a an the is are was were be been being of for to in on at by with and or as from this that these those it its they them their he she his her who what which when where why how do does did can could would should will about tell explain describe please me you your book text passage answer question'.split())


def normalized(value: str) -> str:
    return ' '.join(value.split()).casefold()


def content_words(value: str) -> set[str]:
    words = set(re.findall(r"[a-z]+|\d+", value.casefold())) - STOP_WORDS
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word for word in words}


def metadata_intent(question: str) -> list[str]:
    """Recognize direct book identity questions, not questions about chapter titles."""
    text = re.sub(r"[^a-z0-9' ]", ' ', question.casefold())
    text = ' '.join(text.split())
    if re.search(r'\b(chapter|meaning|significance|why)\b', text):
        return []
    fields = []
    if re.search(r"^(what(?:'s| is)?|tell me|give me|name).{0,30}\b(title|name of (?:this|the) book)\b", text) or re.search(r'^what is (?:this|the) book called', text):
        fields.append('title')
    if re.search(r'\bwho (?:is |was )?(?:the )?author\b|\bwho wrote\b', text) or (fields and 'author' in text):
        fields.append('author')
    return fields


@dataclass
class GroundedAnswer:
    payload: dict
    sources: list[dict]


def insufficient() -> GroundedAnswer:
    return GroundedAnswer({'status': 'insufficient_evidence', 'method': 'model',
        'content': INSUFFICIENT, 'statements': []}, [])


def metadata_answer(book: dict, fields: list[str]) -> GroundedAnswer | None:
    """Answer title/author directly from stated PDF metadata, with metadata citations."""
    if not fields or not all(book.get(field) for field in fields):
        return None
    statements = []
    sources = []
    for rank, field in enumerate(fields, start=1):
        label = 'title' if field == 'title' else 'author'
        statements.append({'text': f"The {label} is {book[field]}.", 'citation_ranks': [rank]})
        sources.append({'source_kind': 'metadata', 'chunk_id': None, 'quote': book[field]})
    content = '\n\n'.join(row['text'] + ' ' + ''.join(f'[{rank}]' for rank in row['citation_ranks']) for row in statements)
    return GroundedAnswer({'status': 'answered', 'method': 'metadata', 'content': content, 'statements': statements}, sources)


def validate_answer(answer: ModelAnswer, evidence: list[dict]) -> GroundedAnswer:
    """Reject invented IDs/quotes/pages and conservatively filter unrelated claims.

    Literal quote checks establish provenance, not perfect logical entailment;
    semantic groundedness is also evaluated in reviewed live test questions.
    """
    if not answer.supported or not answer.statements:
        return insufficient()
    available = {source['source_id']: source for source in evidence}
    sources = []
    ranks = {}
    statements = []
    for statement in answer.statements:
        text = statement.text.strip()
        if re.search(r'\[\d+\]|\bpages?\s+\d+', text, re.IGNORECASE):
            return insufficient()
        statement_ranks = []
        quote_text = []
        for reference in statement.citations:
            source = available.get(reference.source_id)
            quote = ' '.join(reference.quote.split()).strip()
            if not source or not 12 <= len(quote) <= 600 or normalized(quote) not in normalized(source['content']):
                return insufficient()
            identity = (reference.source_id, normalized(quote))
            if identity not in ranks:
                ranks[identity] = len(sources) + 1
                sources.append({'source_kind': 'passage', 'chunk_id': source['id'], 'quote': quote})
            rank = ranks[identity]
            if rank not in statement_ranks:
                statement_ranks.append(rank)
            quote_text.append(quote)
        # This extra check rejects obvious disjoint claims and invented numbers.
        words = content_words(text)
        quoted_words = content_words(' '.join(quote_text))
        numbers = set(re.findall(r'\d+', text))
        if not statement_ranks or (words and len(words & quoted_words) / len(words) < 0.6) or not numbers <= set(re.findall(r'\d+', ' '.join(quote_text))):
            return insufficient()
        statements.append({'text': text, 'citation_ranks': statement_ranks})
    content = '\n\n'.join(row['text'] + ' ' + ''.join(f'[{rank}]' for rank in row['citation_ranks']) for row in statements)
    return GroundedAnswer({'status': 'answered', 'method': 'model', 'content': content, 'statements': statements}, sources)

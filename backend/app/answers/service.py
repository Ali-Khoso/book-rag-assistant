"""Question answering: retrieve, generate, verify, then atomically save a turn."""

import re

from app.answers.grounding import content_words, insufficient, metadata_answer, metadata_intent, validate_answer
from app.answers.llm import ModelUnavailable
from app.answers.overview import overview_evidence, overview_intent, overview_scope
from app.processing.errors import ProcessingError
from app.processing.metadata import read_pdf_metadata


class ChatConflict(Exception):
    """A book/conversation changed while this question was being prepared."""


def question_needs_history(question: str) -> bool:
    """Keep standalone questions free of unrelated previous topics.

    Pronouns and short continuation prompts use recent turns for disambiguation;
    mentioning the selected book itself does not require the old transcript.
    """
    text = re.sub(r'\b(this|that|the|my) (book|document|pdf)\b', 'book', question.casefold())
    return bool(re.search(r'\b(it|they|them|he|she|his|her|their|that|those|these|this|more|else|continue|expand|elaborate)\b|\b(?:which|what) one\b', text)
        or text.strip().startswith(('and ', 'what about ', 'how about '))
        or re.fullmatch(r'\s*(why|how|why not)[?!.\s]*', text))


class AnswerService:
    def __init__(self, books, chats, embeddings, language_model, config):
        self.books = books
        self.chats = chats
        self.embeddings = embeddings
        self.language_model = language_model
        self.config = config

    def ask(self, owner: str, book: dict, request) -> dict:
        """Only the verified owner and selected book enter the generation context."""
        if not book.get('metadata_checked'):
            try:
                metadata = read_pdf_metadata(self.books.download(book))
                if not self.books.save_metadata(book, metadata):
                    raise ChatConflict('The book changed. Refresh and try again.')
                book = {**book, **metadata, 'metadata_checked': True}
            except ChatConflict:
                raise
            except Exception as exc:
                raise ModelUnavailable('Could not read this book’s details. Please try again.') from exc
        request_id = str(request.request_id)
        conversation_id = str(request.conversation_id) if request.conversation_id else None
        claim = self.chats.begin(owner, book['id'], request_id, request.question, conversation_id)
        if claim['state'] == 'completed':
            return claim['response']
        if claim['state'] == 'busy':
            raise ChatConflict('Another answer is being prepared in this conversation. Please wait a moment.')
        try:
            fields = metadata_intent(request.question)
            result = metadata_answer(book, fields)
            if result is None:
                if book.get('embedding_model') != self.embeddings.model_id:
                    raise ChatConflict('Reprocess this book before asking questions with the current search model.')
                history, _ = self.chats.message_page(str(claim['conversation_id']), limit=self.config.conversation_history_turns * 2)
                is_overview = overview_intent(request.question)
                context_history = history if not is_overview and question_needs_history(request.question) else []
                evidence = self._evidence(owner, book, request, context_history, fields)
                if not evidence:
                    result = insufficient()
                else:
                    generated = self.language_model.generate(request.question, evidence, context_history)
                    result = validate_answer(generated, evidence)
                    if is_overview and result.payload['status'] == 'answered':
                        result.payload['scope_note'] = overview_scope(evidence)
            return self.chats.finish(owner, book['id'], request_id, result.payload, result.sources)
        except Exception:
            try:
                self.chats.abort(owner, request_id)
            except Exception:
                pass
            raise

    def _evidence(self, owner: str, book: dict, request, history: list[dict], fields: list[str]) -> list[dict]:
        """Identity uses opening pages, overviews span the book, and topics use search."""
        if not fields and overview_intent(request.question):
            return overview_evidence(self.books.overview_passages(owner, book), book,
                limit=min(request.top_k, self.config.answer_retrieval_k), budget=self.config.answer_context_chars)
        query = request.question
        if not fields and history and question_needs_history(query):
            prior = next((row['content'] for row in reversed(history) if row['role'] == 'user'), '')
            query = query + '\nPrevious question: ' + prior[:500]
        if fields:
            rows = self.books.opening_passages(book)
        else:
            try:
                vector = self.embeddings.embed([query])[0]
            except ProcessingError as exc:
                raise ModelUnavailable('Book search is temporarily unavailable. Please try again.') from exc
            rows = self.books.search(owner, book['id'], vector, self.embeddings.model_id, min(request.top_k, self.config.answer_retrieval_k))
            rows = [row for row in rows if row.get('similarity', 0) >= self.config.answer_min_similarity]
            # Nearest neighbours alone do not prove answerability. Obvious topic
            # mismatches abstain before a model can fill the gap from world knowledge.
            words = content_words(query)
            if words and not any(words & content_words(row['content']) for row in rows):
                return []
        evidence = []
        size = 0
        for row in rows:
            if row.get('document_id') != book['id']:
                continue
            if size + len(row['content']) > self.config.answer_context_chars:
                continue
            evidence.append({**row, 'source_id': f's{len(evidence) + 1}'})
            size += len(row['content'])
        return evidence

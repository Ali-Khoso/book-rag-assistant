"""Answer API ownership: no foreign book or conversation can reach the model."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import VerifiedUser, require_user
from tests.test_api_ownership import BOOK, OWNER, OTHER
from tests.test_processing_pipeline import test_config

CONVERSATION = str(uuid4())
NOW = '2026-10-27T00:00:00Z'


def client(owner=OWNER, status='ready'):
    books, chats, embeddings, model = Mock(), Mock(), Mock(model_id='test-model'), Mock()
    book = {'id': BOOK, 'user_id': OWNER, 'filename': 'book.pdf', 'title': 'Field Notes', 'author': 'Ada Reader',
        'metadata_checked': True, 'status': status, 'created_at': NOW, 'page_count': 4, 'chunk_count': 5, 'embedding_model': 'test-model'}
    books.get_document.side_effect = lambda document, user: book if document == BOOK and user == OWNER else None
    summary = {'id': CONVERSATION, 'document_id': BOOK, 'title': 'Question', 'created_at': NOW, 'updated_at': NOW}
    chats.get_conversation.side_effect = lambda user, conversation: summary if user == OWNER and conversation == CONVERSATION else None
    chats.list_conversations.return_value = [summary]
    chats.message_page.return_value = ([], False)
    chats.begin.return_value = {'state': 'started', 'conversation_id': CONVERSATION}
    chats.finish.side_effect = lambda user, document, request, payload, sources: {
        'conversation_id': CONVERSATION, 'request_id': request, 'document_id': BOOK, 'question': 'What is the title?',
        'user_message_id': str(uuid4()), 'message_id': str(uuid4()), 'created_at': NOW, 'answer': {**payload, 'citations': []}}
    application = create_app(books, embeddings, test_config(), worker_enabled=False, chat_repository=chats, language_model=model)
    if owner: application.dependency_overrides[require_user] = lambda: VerifiedUser(owner)
    return TestClient(application), books, chats, model


@pytest.mark.parametrize('path,method', [
    (f'/api/documents/{BOOK}/ask', 'POST'), (f'/api/documents/{BOOK}/conversations', 'GET'),
    (f'/api/documents/{BOOK}', 'GET'), (f'/api/conversations/{CONVERSATION}', 'GET'),
    (f'/api/conversations/{CONVERSATION}', 'DELETE'),
])
def test_other_owner_cannot_access_chat(path, method):
    api, books, chats, model = client(OTHER)
    response = api.request(method, path, json={'question': 'private facts'})
    assert response.status_code == 404
    model.generate.assert_not_called(); chats.begin.assert_not_called(); chats.message_page.assert_not_called(); chats.delete_conversation.assert_not_called()


def test_unauthenticated_ask_rejected_before_book_access():
    api, books, chats, model = client(None)
    assert api.post(f'/api/documents/{BOOK}/ask', json={'question': 'What is the title?'}).status_code == 401
    books.get_document.assert_not_called()


@pytest.mark.parametrize('status', ['queued', 'processing', 'failed'])
def test_only_ready_books_allow_questions(status):
    api, books, chats, model = client(status=status)
    assert api.post(f'/api/documents/{BOOK}/ask', json={'question': 'What is the title?'}).status_code == 409
    chats.begin.assert_not_called()


def test_conversation_is_bound_to_its_original_book():
    api, books, chats, model = client()
    chats.get_conversation.return_value = None
    chats.get_conversation.side_effect = None
    assert api.post(f'/api/documents/{BOOK}/ask', json={'question': 'What is the title?', 'conversation_id': CONVERSATION}).status_code == 404
    chats.begin.assert_not_called()


def test_own_conversation_cannot_be_reused_for_a_different_book():
    api, books, chats, model = client()
    second_book = str(uuid4())
    second = {'id': second_book, 'user_id': OWNER, 'status': 'ready'}
    original_lookup = books.get_document.side_effect
    books.get_document.side_effect = lambda document, user: second if document == second_book and user == OWNER else original_lookup(document, user)
    response = api.post(f'/api/documents/{second_book}/ask', json={'question': 'What is the title?', 'conversation_id': CONVERSATION})
    assert response.status_code == 404
    chats.begin.assert_not_called()


def test_metadata_answer_and_pagination_use_verified_owner():
    api, books, chats, model = client()
    response = api.post(f'/api/documents/{BOOK}/ask', json={'question': 'What is the title?', 'user_id': OTHER})
    assert response.status_code == 200 and response.json()['answer']['content'] == 'The title is Field Notes. [1]'
    assert chats.begin.call_args.args[0:2] == (OWNER, BOOK)
    assert api.get(f'/api/conversations/{CONVERSATION}?before_sequence=21').status_code == 200
    chats.message_page.assert_called_once_with(CONVERSATION, before=21)
    model.generate.assert_not_called()


@pytest.mark.parametrize('payload', [{'question': ' '}, {'question': 'x' * 2001}, {'question': 'fact', 'request_id': 'not-a-uuid'}])
def test_answer_request_validation(payload):
    api, books, chats, model = client()
    assert api.post(f'/api/documents/{BOOK}/ask', json=payload).status_code == 422
    chats.begin.assert_not_called()

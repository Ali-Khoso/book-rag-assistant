"""Retrieval testing: API authentication, book ownership, and retry boundaries."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import VerifiedUser, require_user
from tests.test_processing_pipeline import test_config

OWNER = 'c48b8f18-508a-4c91-84dc-8caeea51d8f0'
OTHER = '02e548ad-de81-44bc-ab4a-bdb73c88d5ed'
BOOK = 'ab81914e-663a-4a9d-8696-2081126d327b'


def api_client(owner=OWNER, status='ready', model='test-model'):
    repository = Mock()
    document = {'id': BOOK, 'filename': 'private.pdf', 'user_id': OWNER, 'status': status,
        'storage_key': f'{OWNER}/{BOOK}.pdf', 'page_count': 3, 'created_at': '2026-10-27T00:00:00Z',
        'embedding_model': model, 'chunk_count': 2}
    repository.get_document.side_effect = lambda doc_id, user_id: document if doc_id == BOOK and user_id == OWNER else None
    repository.queue_retry.return_value = {**document, 'status': 'queued'}
    repository.search.return_value = []
    embeddings = Mock(model_id='test-model')
    embeddings.embed.return_value = [[1.0] + [0.0] * 255]
    application = create_app(repository, embeddings, test_config(), worker_enabled=False)
    if owner:
        application.dependency_overrides[require_user] = lambda: VerifiedUser(owner)
    return TestClient(application), repository, embeddings


@pytest.mark.parametrize('action', ['search', 'retry', 'delete'])
def test_other_owner_cannot_search_retry_or_delete(action):
    client, repository, embeddings = api_client(OTHER)
    response = client.delete(f'/api/documents/{BOOK}') if action == 'delete' else client.post(f'/api/documents/{BOOK}/{action}', json={'question': 'private fact'})
    assert response.status_code == 404
    repository.search.assert_not_called()
    repository.queue_retry.assert_not_called()
    repository.delete_document.assert_not_called()
    embeddings.embed.assert_not_called()


def test_missing_authentication_is_rejected_before_storage():
    client, repository, _ = api_client(None)
    assert client.post(f'/api/documents/{BOOK}/search', json={'question': 'fact'}).status_code == 401
    repository.get_document.assert_not_called()


def test_search_supplies_verified_owner_and_selected_book():
    client, repository, _ = api_client()
    response = client.post(f'/api/documents/{BOOK}/search', json={'question': '  Find a fact  ', 'top_k': 3, 'user_id': OTHER})
    assert response.status_code == 200 and response.json()['question'] == 'Find a fact'
    args = repository.search.call_args.args
    assert args[0] == OWNER and args[1] == BOOK and args[-1] == 3


@pytest.mark.parametrize('status', ['queued', 'processing', 'failed'])
def test_only_ready_books_can_be_searched(status):
    client, repository, embeddings = api_client(status=status)
    assert client.post(f'/api/documents/{BOOK}/search', json={'question': 'fact'}).status_code == 409
    repository.search.assert_not_called()
    embeddings.embed.assert_not_called()


def test_retry_conflicts_with_active_processing():
    client, repository, _ = api_client(status='processing')
    assert client.post(f'/api/documents/{BOOK}/retry').status_code == 409
    repository.queue_retry.assert_not_called()


def test_failed_book_can_be_requeued():
    client, repository, _ = api_client(status='failed')
    response = client.post(f'/api/documents/{BOOK}/retry')
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    repository.queue_retry.assert_called_once_with(BOOK, OWNER)


def test_search_cannot_mix_model_versions():
    client, repository, embeddings = api_client(model='old-model')
    assert client.post(f'/api/documents/{BOOK}/search', json={'question': 'fact'}).status_code == 409
    repository.search.assert_not_called()
    embeddings.embed.assert_not_called()


@pytest.mark.parametrize('payload', [{'question': '  '}, {'question': 'x', 'top_k': 11}, {'question': 'x' * 2001}])
def test_search_request_limits(payload):
    client, repository, _ = api_client()
    assert client.post(f'/api/documents/{BOOK}/search', json=payload).status_code == 422
    repository.search.assert_not_called()

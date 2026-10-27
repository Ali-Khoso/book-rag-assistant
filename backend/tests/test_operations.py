"""Phase 4: shared limits, fail-closed behavior, body caps, and private monitoring."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.operations import ControlsUnavailable, LimitExceeded, OperationalControls
from app.processing.pipeline import process_document
from app.processing.worker import ProcessingWorker
from app.repository import SupabaseRepository
from app.security import VerifiedUser, require_user
from tests.pdf_factory import make_pdf
from tests.test_api_ownership import BOOK, OWNER
from tests.test_processing_pipeline import JOB, pipeline_repository, test_config


def operational_client(**options):
    books, controls, embeddings = Mock(), Mock(), Mock(model_id='test-model')
    books.list_documents.return_value = []
    books.get_document.return_value = {'id': BOOK, 'user_id': OWNER, 'status': 'ready', 'embedding_model': 'test-model'}
    books.search.return_value = []
    embeddings.embed.return_value = [[1.0] + [0.0] * 255]
    controls.consume.return_value = None
    controls.health.return_value = {'database': True, 'worker': True, 'cleanup_blocked': 0}
    ready = Mock()
    ready.check.return_value = {'database': True, 'worker': True, 'embeddings': True, 'answers': True}
    app = create_app(books, embeddings, test_config(limits_enabled=True, **options),
        worker_enabled=False, controls=controls, readiness=ready)
    app.dependency_overrides[require_user] = lambda: VerifiedUser(OWNER)
    return TestClient(app), books, controls, ready


def test_shared_rate_limit_returns_retry_after_before_expensive_work():
    client, books, controls, _ = operational_client()
    controls.consume.side_effect = LimitExceeded(17, 'search')
    response = client.post(f'/api/documents/{BOOK}/search', json={'question': 'Find a fact'}, headers={'Origin': 'http://localhost:3000'})
    assert response.status_code == 429 and response.headers['Retry-After'] == '17'
    assert 'Retry-After' in response.headers['access-control-expose-headers']
    books.get_document.assert_not_called(); books.search.assert_not_called()
    controls.consume.assert_called_once_with(OWNER, 'search', None)


def test_limits_fail_closed_without_leaking_database_errors():
    client, books, controls, _ = operational_client()
    controls.consume.side_effect = ControlsUnavailable('Usage checks are temporarily unavailable. Please try again.')
    assert client.get('/api/documents').status_code == 503
    books.list_documents.assert_not_called()


def test_completed_question_uuid_is_passed_to_budget_deduplication():
    client, books, controls, _ = operational_client()
    books.get_document.return_value = None
    request_id = 'abbc912a-56e7-4d47-80b4-ae90e90f804b'
    response = client.post(f'/api/documents/{BOOK}/ask', json={'question': 'Fact', 'request_id': request_id, 'user_id': 'forged-owner'})
    assert response.status_code == 404
    assert controls.consume.call_args.args[0:2] == (OWNER, 'ask')
    assert str(controls.consume.call_args.args[2]) == request_id


def test_database_control_uses_atomic_rpc_and_safe_outage_error():
    client = Mock()
    control = OperationalControls(client, test_config(limits_enabled=True))
    client.rpc.return_value.execute.return_value.data = {'allowed': False, 'retry_after': 9}
    with pytest.raises(LimitExceeded): control.consume(OWNER, 'ask')
    assert client.rpc.call_args.args[0] == 'phase4_consume_usage'
    assert client.rpc.call_args.args[1]['p_user_id'] == OWNER
    client.rpc.side_effect = RuntimeError('private-database-credential')
    with pytest.raises(ControlsUnavailable) as error: control.consume(OWNER, 'ask')
    assert 'private-database' not in str(error.value)


def test_content_length_cap_rejects_before_auth_storage_or_models():
    client, books, controls, _ = operational_client(max_json_body_bytes=4096)
    response = client.post(f'/api/documents/{BOOK}/search', content=b'x' * 5000, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    controls.consume.assert_not_called(); books.get_document.assert_not_called()


def test_streaming_body_cap_cannot_be_bypassed_by_omitting_content_length():
    client, books, controls, _ = operational_client(max_json_body_bytes=4096)
    def chunks():
        yield b'{"question":"'
        yield b'x' * 5000
        yield b'"}'
    response = client.post(f'/api/documents/{BOOK}/search', content=chunks(), headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    books.get_document.assert_not_called()


def test_private_monitoring_and_readiness_fail_when_dependencies_are_down():
    token = 'unit-monitoring-token-with-32-characters'
    client, books, controls, ready = operational_client(monitoring_token=token)
    assert client.get('/api/metrics').status_code == 401
    assert client.get('/api/metrics', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/api/metrics', headers={'Authorization': 'Bearer ' + token}).status_code == 200
    assert client.get('/api/live').status_code == 200
    ready.check.return_value = {'database': True, 'worker': False, 'embeddings': True, 'answers': True}
    assert client.get('/api/ready').status_code == 503


def test_headers_and_trusted_hosts_apply_to_error_responses():
    client, *_ = operational_client()
    response = client.get('/api/health', headers={'Host': 'attacker.example'})
    assert response.status_code == 400
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Request-ID'] and response.headers['Cache-Control'] == 'no-store'


def test_request_logs_omit_question_credentials_and_raw_document_id(caplog):
    client, *_ = operational_client()
    with caplog.at_level(logging.INFO, logger='app.operations'):
        client.post(f'/api/documents/{BOOK}/search', json={'question': 'PRIVATE-QUESTION-MUST-NOT-BE-LOGGED'},
            headers={'Authorization': 'Bearer PRIVATE-TOKEN-MUST-NOT-BE-LOGGED'})
    records = [row for row in caplog.records if getattr(row, 'event', '') == 'http_request']
    assert records and records[-1].fields['route'] == '/api/documents/{document_id}/search'
    assert all(secret not in str(records[-1].fields) for secret in [BOOK, 'PRIVATE-QUESTION', 'PRIVATE-TOKEN'])


def test_invalid_pdf_is_permanent_but_storage_outage_is_retryable():
    bad = pipeline_repository(b'not a PDF')
    process_document(JOB, bad, Mock(), test_config())
    assert bad.fail.call_args.kwargs == {'retryable': False}
    unavailable = pipeline_repository(make_pdf(['Readable text']))
    unavailable.download.side_effect = TimeoutError('private-storage-details')
    process_document(JOB, unavailable, Mock(), test_config())
    assert unavailable.fail.call_args.kwargs == {'retryable': True}
    assert 'private-storage' not in unavailable.fail.call_args.args[1]


def test_worker_prioritizes_durable_deletion_and_does_not_delete_foreign_paths():
    repository = Mock()
    repository.claim_deletion.return_value = {'id': BOOK}
    worker = ProcessingWorker(repository, Mock(), test_config())
    assert worker.process_once()
    repository.clean_deletion.assert_called_once(); repository.claim_next.assert_not_called()
    client = Mock()
    real = SupabaseRepository(client, test_config())
    with pytest.raises(ValueError): real.clean_deletion({'id': BOOK, 'user_id': OWNER, 'storage_key': 'other-owner/private.pdf'})
    client.storage.from_.assert_not_called()


def test_failed_file_cleanup_retains_row_and_records_durable_retry():
    client = Mock()
    client.storage.from_.return_value.remove.side_effect = TimeoutError('private-storage-details')
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=True)
    repository = SupabaseRepository(client, test_config())
    row = {'id': BOOK, 'user_id': OWNER, 'storage_key': f'{OWNER}/{BOOK}.pdf', 'deletion_claim_id': 'claim'}
    assert repository.clean_deletion(row) is False
    assert client.rpc.call_args.args[0] == 'phase4_fail_deletion'
    client.table.assert_not_called()


def test_production_rejects_http_origins_disabled_limits_and_wildcard_hosts():
    common = {'environment': 'production', 'frontend_origin': 'https://books.example.com', 'allowed_hosts': ['books.example.com'], 'limits_enabled': True}
    for invalid in [{'frontend_origin': 'http://localhost:3000'}, {'limits_enabled': False}, {'allowed_hosts': ['*']}]:
        with pytest.raises(ValidationError): test_config(**{**common, **invalid})

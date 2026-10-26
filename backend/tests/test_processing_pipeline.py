"""Processing status and retry: failure cleanup, model checks, and lease safety."""

from unittest.mock import Mock

import pytest

from app.config import Settings
from app.processing.embeddings import EmbeddingService
from app.processing.errors import ProcessingError
from app.processing.pipeline import process_document
from tests.pdf_factory import make_pdf


def test_config(**overrides):
    return Settings(_env_file=None, supabase_url='https://test.supabase.co',
        supabase_publishable_key='test-public', supabase_secret_key='test-secret', **overrides)
test_config.__test__ = False


JOB = {'id': 'book-id', 'user_id': 'owner-id', 'processing_run_id': 'run-id'}


def pipeline_repository(content):
    repository = Mock()
    repository.progress.return_value = True
    repository.download.return_value = content
    repository.append_chunks.side_effect = lambda job, rows: len(rows)
    repository.finish.return_value = True
    return repository


def test_pipeline_saves_page_metadata_and_completes():
    repository = pipeline_repository(make_pdf(['Evidence on page one.', '', 'Evidence on page three.']))
    embeddings = Mock()
    embeddings.embed.side_effect = lambda texts: [[1.0] + [0.0] * 255 for _ in texts]
    process_document(JOB, repository, embeddings, test_config())
    rows = repository.append_chunks.call_args.args[1]
    assert rows[0]['page_start'] == 1 and rows[0]['page_end'] == 3
    assert len(rows[0]['embedding']) == 256
    repository.finish.assert_called_once_with(JOB, 3, len(rows))
    repository.fail.assert_not_called()


def test_model_failure_records_safe_message_and_never_marks_ready():
    repository = pipeline_repository(make_pdf(['A readable passage for embedding.']))
    embeddings = Mock()
    embeddings.embed.side_effect = ProcessingError('The model is unavailable. Retry later.')
    process_document(JOB, repository, embeddings, test_config())
    repository.fail.assert_called_once_with(JOB, 'The model is unavailable. Retry later.')
    repository.finish.assert_not_called()


def test_unexpected_failure_hides_provider_credentials():
    repository = pipeline_repository(make_pdf(['Readable passage.']))
    repository.download.side_effect = RuntimeError('secret-token=do-not-show')
    process_document(JOB, repository, Mock(), test_config())
    assert 'secret-token' not in repository.fail.call_args.args[1]


def test_lost_lease_does_not_write_failure_or_more_chunks():
    repository = pipeline_repository(make_pdf(['Readable passage.']))
    repository.progress.return_value = False
    process_document(JOB, repository, Mock(), test_config())
    repository.download.assert_not_called()
    repository.append_chunks.assert_not_called()
    repository.fail.assert_not_called()


@pytest.mark.parametrize('vector', [[0.0] * 256, [1.0] * 255, [float('nan')] * 256])
def test_embeddings_reject_zero_nonfinite_and_wrong_dimensions(vector):
    service = EmbeddingService(test_config(embedding_provider='api', embedding_api_url='https://example.com/embeddings', embedding_api_key='private'))
    service._embed_api = Mock(return_value=[vector])
    with pytest.raises(ProcessingError):
        service.embed(['question'])


def test_embedding_normalization_and_model_space_isolation():
    service = EmbeddingService(test_config(embedding_provider='api', embedding_api_url='https://example.com/embeddings', embedding_api_key='private'))
    service._embed_api = Mock(return_value=[[3.0, 4.0] + [0.0] * 254])
    assert service.embed(['question'])[0][:2] == [0.6, 0.8]
    other = EmbeddingService(test_config(embedding_model='another-model'))
    assert service.model_id != other.model_id
    assert 'private' not in service.model_id

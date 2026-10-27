"""Grounded answers: provenance, abstention, metadata, and provider failure safety."""

import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from app.answers.grounding import metadata_answer, metadata_intent, validate_answer
from app.answers.llm import LanguageModel, ModelUnavailable
from app.answers.models import AskRequest, ModelAnswer
from app.answers.service import AnswerService, ChatConflict, question_needs_history
from app.processing.metadata import read_pdf_metadata
from tests.pdf_factory import make_pdf
from tests.test_processing_pipeline import test_config

BOOK = {'id': str(uuid4()), 'user_id': 'owner', 'title': 'Field Notes', 'author': 'Ada Reader', 'metadata_checked': True, 'embedding_model': 'test-model'}
TEXT = 'Plants release oxygen as a byproduct during photosynthesis.'
EVIDENCE = [{'source_id': 's1', 'id': str(uuid4()), 'document_id': BOOK['id'], 'content': TEXT, 'similarity': .8, 'page_start': 3, 'page_end': 3}]


def model_answer(text=TEXT, quote=TEXT, source='s1'):
    return ModelAnswer(supported=True, statements=[{'text': text, 'citations': [{'source_id': source, 'quote': quote}]}])


@pytest.mark.parametrize('question,fields', [
    ('what is the title\n?', ['title']), ('Who wrote this book?', ['author']),
    ('What is the title and author?', ['title', 'author']), ('What is the title of chapter 4?', []),
    ('Why is the title significant?', []), ('Explain the meaning of the title', []),
])
def test_metadata_intent_is_limited_to_book_identity(question, fields):
    assert metadata_intent(question) == fields


def test_metadata_is_read_from_pdf_and_never_guessed_from_filename():
    metadata = read_pdf_metadata(make_pdf(['Readable text.'], metadata={'/Title': 'Field Notes', '/Author': 'Ada Reader'}))
    assert metadata == {'title': 'Field Notes', 'author': 'Ada Reader'}
    result = metadata_answer(metadata, ['title', 'author'])
    assert result.payload['content'] == 'The title is Field Notes. [1]\n\nThe author is Ada Reader. [2]'
    assert all(source['chunk_id'] is None for source in result.sources)
    assert metadata_answer({'title': None}, ['title']) is None
    assert read_pdf_metadata(make_pdf(['Text'], metadata={'/Title': 'Untitled'}))['title'] is None


def test_supported_quote_is_linked_only_to_supplied_chunk():
    result = validate_answer(model_answer(), EVIDENCE)
    assert result.payload['status'] == 'answered'
    assert result.payload['content'].endswith('[1]')
    assert result.sources == [{'source_kind': 'passage', 'chunk_id': EVIDENCE[0]['id'], 'quote': TEXT}]
    assert 'page_start' not in result.sources[0]  # SQL derives pages independently.


@pytest.mark.parametrize('answer', [
    model_answer(source='invented'), model_answer(quote='This quotation was never in the book.'),
    model_answer(text='The answer is on page 999.'), model_answer(text=TEXT + ' [99]'),
    model_answer(text='Plants release 500 kilograms of oxygen.'),
    model_answer(text='Napoleon won a battle in Paris.'),
    ModelAnswer(supported=False, statements=[]), ModelAnswer(supported=True, statements=[]),
])
def test_missing_or_invalid_evidence_abstains_without_fake_sources(answer):
    result = validate_answer(answer, EVIDENCE)
    assert result.payload['status'] == 'insufficient_evidence'
    assert result.sources == []


@pytest.mark.parametrize('provider', ['ollama', 'openai'])
def test_provider_uses_strict_source_schema_and_keeps_keys_out_of_prompt(provider):
    def handler(request):
        body = json.loads(request.content)
        serialized = request.content.decode()
        assert 'private-test-key' not in serialized
        if provider == 'openai':
            assert str(request.url) == 'https://api.openai.com/v1/responses'
            assert request.headers['Authorization'] == 'Bearer private-test-key'
            assert body['store'] is False and body['text']['format']['strict'] is True
            schema = body['text']['format']['schema']
            result = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': model_answer().model_dump_json()}]}]}
        else:
            assert request.url.path == '/api/chat' and body['stream'] is False
            schema = body['format']
            assert 'untrusted data' in body['messages'][0]['content']
            result = {'message': {'content': model_answer().model_dump_json()}}
        assert schema['properties']['statements']['items']['properties']['citations']['items']['properties']['source_id']['enum'] == ['s1']
        return httpx.Response(200, json=result)
    overrides = {'llm_provider': provider}
    if provider == 'openai':
        overrides.update(llm_model='test-structured-model', openai_api_key='private-test-key')
    result = LanguageModel(test_config(**overrides), transport=httpx.MockTransport(handler)).generate('Which gas?', EVIDENCE, [])
    assert result.supported


@pytest.mark.parametrize('body,status', [({'message': {'content': 'broken json'}}, 200), ({'error': 'private provider details'}, 500), ({'message': {}}, 200)])
def test_provider_failures_are_safe_errors_not_unsupported_answers(body, status):
    model = LanguageModel(test_config(), transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)))
    with pytest.raises(ModelUnavailable) as error:
        model.generate('Question', EVIDENCE, [])
    assert 'private provider details' not in str(error.value)


def test_truncated_local_generation_is_a_retryable_failure():
    model = LanguageModel(test_config(), transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={'done_reason': 'length', 'message': {'content': model_answer().model_dump_json()}})))
    with pytest.raises(ModelUnavailable): model.generate('Question', EVIDENCE, [])


def test_history_is_bounded_and_never_mixed_into_evidence():
    def handler(request):
        user = json.loads(json.loads(request.content)['messages'][1]['content'])
        assert list(user)[-1] == 'current_question'
        assert user['current_question'] == 'Question'
        assert sum(len(row['content']) for row in user['conversation_context']) <= 3000
        assert user['evidence'] == [{'source_id': 's1', 'text': TEXT}]
        assert all(len(row['content']) <= 750 for row in user['conversation_context'])
        return httpx.Response(200, json={'message': {'content': model_answer().model_dump_json()}})
    history = [{'role': 'assistant', 'content': 'Unverified prior claim. ' * 200} for _ in range(12)]
    LanguageModel(test_config(), transport=httpx.MockTransport(handler)).generate('Question', EVIDENCE, history)


def services():
    books, chats, embeddings, model = Mock(), Mock(), Mock(model_id='test-model'), Mock()
    chats.begin.return_value = {'state': 'started', 'conversation_id': str(uuid4())}
    chats.message_page.return_value = ([], False)
    chats.finish.side_effect = lambda owner, book, request, payload, sources: {'answer': payload, 'sources': sources}
    books.search.return_value = EVIDENCE
    embeddings.embed.return_value = [[1.0] + [0.0] * 255]
    model.generate.return_value = model_answer()
    return AnswerService(books, chats, embeddings, model, test_config()), books, chats, embeddings, model


def test_completed_request_returns_saved_turn_without_generating_again():
    service, books, chats, embeddings, model = services()
    chats.begin.return_value = {'state': 'completed', 'response': {'saved': True}}
    assert service.ask('owner', BOOK, AskRequest(question='Which gas?')) == {'saved': True}
    model.generate.assert_not_called(); books.search.assert_not_called(); chats.finish.assert_not_called()


def test_metadata_questions_skip_model_and_irrelevant_vector_search():
    service, books, chats, embeddings, model = services()
    result = service.ask('owner', BOOK, AskRequest(question='What is the title?'))
    assert 'Field Notes' in result['answer']['content']
    model.generate.assert_not_called(); embeddings.embed.assert_not_called(); books.search.assert_not_called()


def test_unrelated_question_abstains_before_language_model_call():
    service, books, chats, embeddings, model = services()
    result = service.ask('owner', BOOK, AskRequest(question='Who invented cryptocurrency?'))
    assert result['answer']['status'] == 'insufficient_evidence'
    model.generate.assert_not_called()


def test_retrieval_is_scoped_to_owner_book_and_context_budget():
    service, books, chats, embeddings, model = services()
    other = {**EVIDENCE[0], 'document_id': 'foreign-book'}
    books.search.return_value = [other, *EVIDENCE]
    service.ask('owner', BOOK, AskRequest(question='Which gas do plants release?'))
    assert books.search.call_args.args[:2] == ('owner', BOOK['id'])
    assert len(model.generate.call_args.args[1]) == 1
    assert model.generate.call_args.args[1][0]['document_id'] == BOOK['id']


def test_failed_generation_releases_conversation_for_retry():
    service, books, chats, embeddings, model = services()
    model.generate.side_effect = ModelUnavailable('Please retry.')
    request = AskRequest(question='Which gas do plants release?')
    with pytest.raises(ModelUnavailable): service.ask('owner', BOOK, request)
    chats.abort.assert_called_once_with('owner', str(request.request_id))
    chats.finish.assert_not_called()


def test_active_turn_conflict_does_not_unlock_another_request():
    service, books, chats, embeddings, model = services()
    chats.begin.return_value = {'state': 'busy'}
    with pytest.raises(ChatConflict): service.ask('owner', BOOK, AskRequest(question='Which gas?'))
    chats.abort.assert_not_called(); model.generate.assert_not_called()


def test_missing_metadata_uses_opening_pages_not_random_title_search():
    service, books, chats, embeddings, model = services()
    books.opening_passages.return_value = [{**EVIDENCE[0], 'content': 'The title is Field Notes.'}]
    model.generate.return_value = model_answer('The title is Field Notes.', 'The title is Field Notes.')
    result = service.ask('owner', {**BOOK, 'title': None}, AskRequest(question='What is the title?'))
    assert result['answer']['status'] == 'answered'
    books.opening_passages.assert_called_once()
    embeddings.embed.assert_not_called(); books.search.assert_not_called()


def test_previously_uploaded_book_reads_metadata_without_reindexing():
    service, books, chats, embeddings, model = services()
    books.download.return_value = make_pdf(['Text'], metadata={'/Title': 'Existing Book'})
    books.save_metadata.return_value = True
    result = service.ask('owner', {**BOOK, 'metadata_checked': False}, AskRequest(question='What is the title?'))
    assert 'Existing Book' in result['answer']['content']
    assert books.save_metadata.call_args.args[0]['user_id'] == 'owner'
    model.generate.assert_not_called(); books.append_chunks.assert_not_called()


def test_changed_book_cannot_save_metadata_or_reserve_a_turn():
    service, books, chats, embeddings, model = services()
    books.download.return_value = make_pdf(['Text'])
    books.save_metadata.return_value = False
    with pytest.raises(ChatConflict):
        service.ask('owner', {**BOOK, 'metadata_checked': False}, AskRequest(question='What is the title?'))
    chats.begin.assert_not_called()


def test_standalone_question_does_not_inherit_unrelated_conversation_topic():
    service, books, chats, embeddings, model = services()
    chats.message_page.return_value = ([{'role': 'user', 'content': 'What is the title?'}, {'role': 'assistant', 'content': 'The title is Field Notes.'}], False)
    service.ask('owner', BOOK, AskRequest(question='Which gas do plants release during photosynthesis?'))
    assert model.generate.call_args.args[2] == []


def test_followup_retains_history_and_expands_only_its_owned_book_query():
    service, books, chats, embeddings, model = services()
    history = [{'role': 'user', 'content': 'Which gas do plants release during photosynthesis?'}, {'role': 'assistant', 'content': TEXT}]
    chats.message_page.return_value = (history, False)
    service.ask('owner', BOOK, AskRequest(question='What do they release?'))
    assert model.generate.call_args.args[2] == history
    assert 'photosynthesis' in embeddings.embed.call_args.args[0][0]
    assert books.search.call_args.args[:2] == ('owner', BOOK['id'])


@pytest.mark.parametrize('question,expected', [('Why?', True), ('Tell me more', True), ('How do they navigate?', True), ('What about that method?', True), ('How do birds navigate?', False), ('What does this book say about birds?', False)])
def test_context_is_requested_only_for_followups(question, expected):
    assert question_needs_history(question) is expected

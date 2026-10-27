"""A maintained quality suite must reject wrong pages and unsupported citations."""

from evaluation.suite import check_answer, load_cases


def test_reviewed_dataset_has_positive_negative_metadata_and_followup_cases():
    data = load_cases()
    assert len(data['cases']) == 9
    assert any(case.get('previous_case') for case in data['cases'])
    assert {case['status'] for case in data['cases']} == {'answered','insufficient_evidence'}


def test_evaluation_rejects_an_answer_word_without_an_owned_supporting_quote():
    case = next(case for case in load_cases()['cases'] if case['id'] == 'astronomy')
    response = {'document_id': 'book', 'answer': {'status': 'answered', 'content': 'Jupiter',
        'statements': [{'text':'Jupiter','citation_ranks':[1]}], 'citations': [{'rank':1,'source_kind':'passage',
            'document_id':'book','chunk_id':'foreign','page_start':1,'page_end':1,'quote':'Jupiter is the largest planet.'}]}}
    result = check_answer(case, response, owner='owner', document_id='book', chunks={})
    assert not result['passed'] and not result['checks']['quote_provenance']


def test_evaluation_rejects_fake_citations_on_an_insufficient_answer():
    case = next(case for case in load_cases()['cases'] if case['id'] == 'out-of-book')
    response = {'document_id':'book','answer': {'status':'insufficient_evidence','content':'No evidence', 'statements':[], 'citations':[{'rank':1}]}}
    result = check_answer(case, response, owner='owner', document_id='book', chunks={})
    assert not result['passed'] and not result['checks']['no_invented_sources']

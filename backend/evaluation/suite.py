"""Evaluate citation provenance separately from factual-keyword and page checks."""

import json
from pathlib import Path

from app.answers.grounding import normalized


def load_cases():
    data = json.loads(Path(__file__).with_name('cases.json').read_text(encoding='utf-8'))
    seen = set()
    for case in data['cases']:
        if not case['id'] or case['id'] in seen or not 1 <= len(case['question']) <= 2000:
            raise ValueError('Invalid or duplicate evaluation case')
        if case.get('previous_case') and case['previous_case'] not in seen:
            raise ValueError('A follow-up must follow a known earlier case')
        if case['status'] not in ('answered', 'insufficient_evidence'):
            raise ValueError('Invalid evaluation status')
        if case['status'] == 'answered' and (not case['keywords'] or case['source_kind'] not in ('passage','metadata')):
            raise ValueError('Supported cases need an answer expectation and source kind')
        if any(not isinstance(page, int) or page < 1 for page in case['pages']):
            raise ValueError('Invalid source page')
        seen.add(case['id'])
    if len(seen) < 5:
        raise ValueError('The reviewed evaluation set is unexpectedly small')
    return data


def check_answer(case, response, *, owner, document_id, chunks):
    """No reference answer/text is written to reports; only test IDs and checks."""
    answer = response['answer']
    citations = answer['citations']
    checks = {'status': answer['status'] == case['status'], 'selected_book': response['document_id'] == document_id,
        'keywords': all(word.casefold() in answer['content'].casefold() for word in case['keywords'])}
    if case['status'] == 'insufficient_evidence':
        checks['no_invented_sources'] = not citations and not answer['statements']
    else:
        checks['source_kind'] = bool(citations) and all(source['source_kind'] == case['source_kind'] for source in citations)
        checks['owned_sources'] = all(source['document_id'] == document_id for source in citations)
        checks['pages'] = all(any(source['page_start'] is not None and source['page_start'] <= page <= source['page_end'] for source in citations) for page in case['pages'])
        valid = True
        for source in citations:
            if source['source_kind'] == 'metadata':
                valid &= source['page_start'] is None and source['page_end'] is None and source['quote'] in source['excerpt']
            else:
                chunk = chunks.get(source['chunk_id'])
                valid &= bool(chunk and chunk['user_id'] == owner and chunk['document_id'] == document_id
                    and source['page_start'] == chunk['page_start'] and source['page_end'] == chunk['page_end']
                    and normalized(source['quote']) in normalized(chunk['content']))
        checks['quote_provenance'] = bool(citations) and valid
        available = {source['rank'] for source in citations}
        checks['citation_links'] = bool(answer['statements']) and all(
            statement['citation_ranks'] and set(statement['citation_ranks']) <= available for statement in answer['statements'])
    return {'id': case['id'], 'passed': all(checks.values()), 'checks': checks}

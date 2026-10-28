"""Opt-in live regression: cited overview, history persistence, and owner isolation."""

import os
from uuid import uuid4

from app.answers.grounding import normalized
from app.supabase_client import service_client
from scripts.live_fixture import LiveFixture
from tests.pdf_factory import make_pdf


STORY = [
    'Mira is a village cartographer who studies seasonal flooding along the river. She meets Jonas, a mechanic who repairs weather instruments. They collect rainfall records, interview farmers, mark damaged roads, inspect old bridges, compare notebooks, and plan safe routes between neighboring settlements. Their first survey begins beside the northern bridge, where rising water has covered the lower footpath.',
    'Mira and Jonas carry their weather instruments through the eastern valley. They measure rainfall, record wind direction, repair broken gauges, and compare observations with local farmers. A storm damages the wooden bridge near the mill. The village residents build a temporary crossing while Mira marks dangerous paths on her survey map and Jonas protects the instruments from the rain.',
    'Mira presents her new river map at the village meeting. Farmers, teachers, mechanics, travelers, and boat workers examine the marked roads and compare the flood observations. Jonas explains how the repaired instruments measure rainfall and wind direction. The residents agree to maintain shared weather records, inspect the northern bridge, and post warnings before the next seasonal storm.',
    'Mira and Jonas publish the completed river map for neighboring villages. The map includes safe crossings, flood warning points, damaged roads, and the locations of working weather instruments. Local teachers use the survey notebooks to explain rainfall measurements. Farmers organize regular bridge inspections, travelers choose safer routes, and the village residents continue recording the changing river levels together.',
]


def run():
    if os.environ.get('PHASE3_LIVE_TEST') != '1':
        raise SystemExit('Set PHASE3_LIVE_TEST=1 to use disposable confirmed accounts.')
    with LiveFixture('http://127.0.0.1:8000') as fixture:
        owner, other = fixture.user(), fixture.user()
        response = fixture.request('POST', '/api/documents', owner, files={
            'file': ('overview-regression.pdf', make_pdf(STORY, metadata={'/Title':'The River Map','/Author':'Ada Reader'}), 'application/pdf')})
        response.raise_for_status()
        document = response.json()['id']
        fixture.wait_ready(owner, document)
        response = fixture.request('POST', f'/api/documents/{document}/ask', owner, json={
            'question':'Now give me short summary what is in the book and what is the story?', 'request_id':str(uuid4())})
        response.raise_for_status()
        turn = response.json(); answer = turn['answer']
        assert answer['status'] == 'answered', answer['status']
        assert 'selected passages' in answer['scope_note'] and 'Mira' in answer['content']
        assert answer['citations'] and 1 <= len(answer['statements']) <= 4
        chunks = {row['id']:row for row in service_client.table('chunks').select('*').eq('document_id',document).eq('user_id',owner['id']).execute().data}
        for citation in answer['citations']:
            chunk = chunks[citation['chunk_id']]
            assert normalized(citation['quote']) in normalized(chunk['content'])
            assert citation['document_id'] == document and citation['page_start'] == chunk['page_start']
        history = fixture.request('GET', '/api/conversations/'+turn['conversation_id'], owner)
        history.raise_for_status()
        assert history.json()['messages'][-1]['answer_payload']['scope_note'] == answer['scope_note']
        denied = fixture.request('POST', f'/api/documents/{document}/ask', other,
            json={'question':'Summarize this book','request_id':str(uuid4())})
        assert denied.status_code == 404
        negative = fixture.request('POST', f'/api/documents/{document}/ask', owner,
            json={'question':'Summarize cryptocurrency','request_id':str(uuid4())})
        negative.raise_for_status()
        assert negative.json()['answer']['status'] == 'insufficient_evidence'
        print('PASS: real model overview with verified page citations; scope persists after reload; foreign owner rejected; unrelated summary topic abstains.', flush=True)


if __name__ == '__main__':
    run()

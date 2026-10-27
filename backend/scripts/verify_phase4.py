"""Opt-in end-to-end evaluation, operational limits, and standalone worker checks."""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.supabase_client import service_client
from evaluation.suite import check_answer, load_cases
from scripts.live_fixture import LiveFixture, clear_budget
from tests.pdf_factory import FACT_PAGES, make_pdf


def save_report(report):
    output = Path('.cache/phase4-evaluation.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')


def run():
    if os.environ.get('PHASE4_LIVE_TEST') != '1':
        raise SystemExit('Set PHASE4_LIVE_TEST=1 to create temporary confirmed users and run real model checks.')
    api = os.environ.get('PHASE4_TEST_API_URL', 'http://127.0.0.1:8000')
    dataset = load_cases()
    report = {'dataset_version': dataset['version'], 'provider': settings.llm_provider,
        'model': settings.llm_model, 'passed': False, 'cases': [], 'operations': {}}
    save_report(report)
    with LiveFixture(api) as live:
        health = live.request('GET', '/api/health'); health.raise_for_status()
        assert health.json()['phase'] == '4' and health.json()['processing'] == 'external', 'Run the API with PROCESSING_ENABLED=false and a separate worker'
        ready = live.request('GET', '/api/ready'); ready.raise_for_status()
        assert set(ready.json()['checks']) == {'database','worker','embeddings','answers'}
        a, b = live.user(), live.user()
        pdf = make_pdf([text * 6 for text in FACT_PAGES], metadata={'/Title': dataset['book_title'], '/Author': dataset['book_author']})
        upload = live.request('POST', '/api/documents', a, files={'file': ('phase4-evaluation.pdf', pdf, 'application/pdf')})
        upload.raise_for_status(); document = upload.json()['id']
        book = live.wait_ready(a, document)
        assert book['processing_attempts'] == 1 and book['file_size_bytes'] == len(pdf)
        chunks = service_client.table('chunks').select('id,content,page_start,page_end,user_id,document_id').eq('document_id', document).execute().data
        chunks = {row['id']: row for row in chunks}
        print('PASS: API without an inline worker -> durable upload -> standalone worker -> ready.', flush=True)
        report['operations']['separate_worker'] = True
        save_report(report)

        conversation = None; responses = {}; requests = {}
        for case in dataset['cases']:
            request_id = str(uuid4()); start = time.monotonic()
            response = live.request('POST', f'/api/documents/{document}/ask', a,
                json={'question': case['question'], 'request_id': request_id, 'conversation_id': conversation})
            # Fast hosted models can finish the suite inside one minute. Respect
            # the normal API budget rather than mistaking a 429 for a bad answer.
            for _ in range(2):
                retry_after = int(response.headers.get('Retry-After', '0'))
                if response.status_code != 429 or not 1 <= retry_after <= 60: break
                time.sleep(retry_after)
                response = live.request('POST', f'/api/documents/{document}/ask', a,
                    json={'question': case['question'], 'request_id': request_id, 'conversation_id': conversation})
            response.raise_for_status(); result = response.json()
            checked = check_answer(case, result, owner=a['id'], document_id=document, chunks=chunks)
            checked['duration_ms'] = round((time.monotonic() - start) * 1000)
            report['cases'].append(checked)
            save_report(report)
            assert checked['passed'], 'Evaluation failed: ' + json.dumps(checked)
            conversation = result['conversation_id']; responses[case['id']] = result; requests[case['id']] = request_id
            print('PASS evaluation: ' + case['id'], flush=True)

        # Seed only this test user's counters to exercise real HTTP enforcement
        # without flooding Auth or issuing 100 paid/inference requests.
        service_client.rpc('phase4_consume_usage', {'p_user_id':a['id'],'p_action':'read',
            'p_minute_limit':100000,'p_daily_limit':100000}).execute()
        service_client.table('usage_windows').update({'request_count': settings.read_requests_per_minute})\
            .eq('user_id', a['id']).eq('action', 'read').eq('period', 'minute').execute()
        limited = live.request('GET', '/api/documents', a)
        assert limited.status_code == 429 and int(limited.headers['Retry-After']) > 0
        assert live.request('GET', '/api/documents', b).status_code == 200
        clear_budget(a['id'], 'read', 'minute')
        clear_budget(a['id'], 'ask', 'minute')
        service_client.table('usage_windows').update({'request_count': settings.questions_per_day})\
            .eq('user_id', a['id']).eq('action', 'ask').eq('period', 'day').execute()
        limited = live.request('POST', f'/api/documents/{document}/ask', a,
            json={'question': 'New question', 'request_id': str(uuid4())})
        assert limited.status_code == 429
        cached = live.request('POST', f'/api/documents/{document}/ask', a,
            json={'question': dataset['cases'][4]['question'], 'request_id': requests['photosynthesis'], 'conversation_id': conversation})
        cached.raise_for_status(); assert cached.json() == responses['photosynthesis']
        clear_budget(a['id'], 'ask', 'day'); clear_budget(a['id'], 'ask', 'minute')
        report['operations']['persistent_limits_and_idempotency'] = True
        save_report(report)
        print('PASS: real HTTP minute/day limits, Retry-After, owner isolation, and cached retries.', flush=True)

        pending = str(uuid4())
        service_client.rpc('phase4_begin_turn', {'p_user_id': a['id'], 'p_document_id': document,
            'p_request_id': pending, 'p_question': 'Controlled concurrency fixture', 'p_concurrent_limit': 1}).execute()
        try:
            busy = live.request('POST', f'/api/documents/{document}/ask', a,
                json={'question': 'Concurrent question', 'request_id': str(uuid4())})
            assert busy.status_code == 409
        finally:
            service_client.rpc('phase3_abort_turn', {'p_user_id': a['id'], 'p_request_id': pending}).execute()
        assert live.request('GET', f'/api/documents/{document}', b).status_code == 404
        assert live.request('GET', '/api/conversations/' + conversation, b).status_code == 404
        assert live.request('DELETE', f'/api/documents/{document}', b).status_code == 404
        report['operations']['concurrency_and_ownership'] = True
        save_report(report)

        # Give a synthetic interrupted job a genuine stored PDF, then verify the
        # external worker resumes its persisted retry and increments the attempt.
        recovery = str(uuid4()); recovery_run = str(uuid4()); recovery_pdf = make_pdf(['A recoverable private PDF with readable text.'])
        service_client.rpc('phase4_reserve_upload', {'p_user_id': b['id'], 'p_document_id': recovery,
            'p_filename': 'phase4-recovery.pdf', 'p_size': len(recovery_pdf), 'p_max_books': 20,
            'p_max_bytes': settings.max_storage_bytes_per_user, 'p_max_attempts': 3}).execute()
        service_client.storage.from_(settings.books_bucket).upload(f"{b['id']}/{recovery}.pdf", recovery_pdf, {'content-type':'application/pdf'})
        service_client.table('documents').update({'upload_completed':True,'status':'processing','processing_run_id':recovery_run,
            'processing_attempts':1,'processing_updated_at':datetime.now(timezone.utc).isoformat()}).eq('id',recovery).eq('user_id',b['id']).execute()
        service_client.rpc('phase4_record_failure', {'p_document_id':recovery,'p_user_id':b['id'],'p_run_id':recovery_run,
            'p_error':'Controlled transient test failure','p_retryable':True}).execute()
        waiting = service_client.table('documents').select('status,processing_next_attempt_at').eq('id',recovery).single().execute().data
        assert waiting['status'] == 'queued' and waiting['processing_next_attempt_at']
        service_client.table('documents').update({'processing_next_attempt_at':'2000-01-01T00:00:00Z'}).eq('id',recovery).execute()
        assert live.wait_ready(b,recovery)['processing_attempts'] == 2
        report['operations']['durable_retry'] = True
        save_report(report)
        print('PASS: a persisted transient failure is retried successfully by the separate worker.', flush=True)

        # Hold only this synthetic cleanup lease so the test can distinguish
        # immediate RLS hiding from eventual successful physical deletion.
        created = service_client.table('documents').select('created_at').eq('id',document).single().execute().data['created_at']
        lease_time = (datetime.fromisoformat(created.replace('Z','+00:00')) + timedelta(hours=1)).isoformat()
        service_client.table('documents').update({'deletion_claim_id':str(uuid4()),'deletion_claimed_at':lease_time}).eq('id',document).execute()
        deleted = live.request('DELETE', f'/api/documents/{document}', a); assert deleted.status_code == 204
        assert live.request('GET', f'/api/documents/{document}', a).status_code == 404
        assert live.request('GET', '/api/conversations/' + conversation, a).status_code == 404
        own_headers = {**live.public,'Authorization':'Bearer '+a['token']}
        for table,column,value in [('documents','id',document),('chunks','document_id',document),('conversations','document_id',document),('message_citations','document_id',document)]:
            response=live.client.get(live.base+'/rest/v1/'+table,headers=own_headers,params={column:'eq.'+value,'select':'*'})
            response.raise_for_status(); assert response.json() == []
        assert service_client.table('documents').select('status').eq('id',document).single().execute().data['status'] == 'deleting'
        service_client.table('documents').update({'deletion_claim_id':None,'deletion_claimed_at':None}).eq('id',document).execute()
        live.wait_purged(document)
        assert not service_client.table('chunks').select('id').eq('document_id',document).execute().data
        assert not service_client.table('conversations').select('id').eq('document_id',document).execute().data
        report['operations']['deletion_hiding_and_purge'] = True
        save_report(report)
        print('PASS: deletion immediately hides all sources/history and the worker purges the private file and records.', flush=True)

    report['passed'] = all(row['passed'] for row in report['cases']) and all(report['operations'].values())
    save_report(report)
    print(f'PASS: {len(report["cases"])} evaluation cases and operational checks. Content-free report: .cache/phase4-evaluation.json',flush=True)


if __name__ == '__main__': run()

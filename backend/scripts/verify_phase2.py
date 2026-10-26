"""Opt-in live retrieval/access-control checks with temporary, auto-confirmed users.

Run from backend: $env:PHASE2_LIVE_TEST='1'; python -m scripts.verify_phase2
Creates no email messages. Cleans up only the accounts/files created in this run.
"""

import os
import secrets
import time
from uuid import uuid4

import httpx

from app.config import settings
from app.supabase_client import service_client
from tests.pdf_factory import FACT_PAGES, make_pdf


def run() -> None:
    """Retrieval testing: verify facts/pages, retry, RLS, and two-user isolation."""
    if os.environ.get('PHASE2_LIVE_TEST') != '1':
        raise SystemExit('Set PHASE2_LIVE_TEST=1 to create and clean up temporary test accounts.')
    api = os.environ.get('PHASE2_TEST_API_URL', 'http://127.0.0.1:8000').rstrip('/')
    auth_url = settings.supabase_url.rstrip('/') + '/auth/v1'
    admin = {'apikey': settings.supabase_secret_key, 'Authorization': f'Bearer {settings.supabase_secret_key}'}
    public = {'apikey': settings.supabase_publishable_key}
    users = []
    documents = []
    markers = []
    with httpx.Client(timeout=30, http2=False) as client:
        def request(method, path, *, token=None, **kwargs):
            headers = {'Authorization': f'Bearer {token}'} if token else {}
            response = client.request(method, api + path, headers=headers, **kwargs)
            return response

        def upload(token, owner, filename, content):
            response = request('POST', '/api/documents', token=token, files={'file': (filename, content, 'application/pdf')})
            response.raise_for_status()
            document = response.json()
            documents.append((document['id'], owner, token))
            return document['id']

        def wait_status(token, document_id, wanted='ready'):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = request('GET', '/api/documents', token=token)
                response.raise_for_status()
                row = next(item for item in response.json() if item['id'] == document_id)
                if row['status'] == wanted:
                    return row
                if row['status'] == 'failed' and wanted != 'failed':
                    raise AssertionError('Synthetic PDF failed: ' + str(row.get('processing_error')))
                time.sleep(1)
            raise AssertionError('Processing did not reach ' + wanted)

        try:
            health = request('GET', '/api/health')
            health.raise_for_status()
            assert health.json()['phase'] == '2'
            for label in ('a', 'b'):
                email = f'phase2-test-{label}-{uuid4().hex}@example.com'
                password = secrets.token_urlsafe(28)
                response = client.post(auth_url + '/admin/users', headers=admin,
                    json={'email': email, 'password': password, 'email_confirm': True})
                response.raise_for_status()
                owner = response.json()['id']
                users.append(owner)
                session = client.post(auth_url + '/token?grant_type=password', headers=public,
                    json={'email': email, 'password': password})
                session.raise_for_status()
                markers.append((owner, session.json()['access_token']))
            owner_a, token_a = markers[0]
            owner_b, token_b = markers[1]
            doc_a = upload(token_a, owner_a, 'phase2-evidence.pdf', make_pdf([text * 8 for text in FACT_PAGES]))
            doc_b = upload(token_b, owner_b, 'phase2-other-owner.pdf', make_pdf(['A different private book about baking bread, flour, yeast, and ovens. ' * 15]))
            ready = wait_status(token_a, doc_a)
            wait_status(token_b, doc_b)
            assert ready['page_count'] == 4 and ready['chunk_count'] > 0
            print('PASS: upload -> processing -> ready with preserved page counts.', flush=True)

            # Each reviewed question has a known source page and answer word.
            questions = [
                ('What is the largest planet in our solar system?', 1, 'Jupiter'),
                ('What causes volcanoes to erupt?', 2, 'magma'),
                ('Which gas do plants release during photosynthesis?', 3, 'oxygen'),
                ('How do migratory birds navigate?', 4, 'magnetic'),
            ]
            top_one = 0
            for question, page, word in questions:
                response = request('POST', f'/api/documents/{doc_a}/search', token=token_a,
                    json={'question': question, 'top_k': 3})
                response.raise_for_status()
                passages = response.json()['passages']
                def supports(passage):
                    return passage['page_start'] <= page <= passage['page_end'] and word.lower() in passage['content'].lower()
                assert any(supports(passage) for passage in passages), f'No support for reviewed question on page {page}'
                top_one += bool(passages and supports(passages[0]))
                assert all(passage['document_id'] == doc_a for passage in passages)
            print(f'PASS: 4/4 reviewed questions supported in top 3; {top_one}/4 supported at rank 1.', flush=True)

            # Server and database both reject crossing the selected book's owner.
            for action in ('search', 'retry'):
                response = request('POST', f'/api/documents/{doc_a}/{action}', token=token_b, json={'question': 'private facts'})
                assert response.status_code == 404
            assert request('DELETE', f'/api/documents/{doc_a}', token=token_b).status_code == 404
            assert request('POST', f'/api/documents/{doc_a}/search', json={'question': 'private facts'}).status_code == 401
            other_books = request('GET', '/api/documents', token=token_b).json()
            assert doc_a not in [book['id'] for book in other_books]
            rest_headers = {**public, 'Authorization': f'Bearer {token_b}'}
            rest = client.get(settings.supabase_url.rstrip('/') + '/rest/v1/chunks',
                headers=rest_headers, params={'document_id': 'eq.' + doc_a, 'select': 'id'})
            rest.raise_for_status()
            assert rest.json() == []
            denied = client.post(settings.supabase_url.rstrip('/') + '/rest/v1/rpc/phase2_search',
                headers=rest_headers, json={'p_user_id': owner_a, 'p_document_id': doc_a,
                    'p_query': [1.0] + [0.0] * 255, 'p_model': 'test', 'p_limit': 3})
            assert denied.status_code in (401, 403)
            print('PASS: cross-user search, retry, deletion, lists, direct chunk reads, and forged-owner RPC calls blocked.', flush=True)

            response = request('POST', f'/api/documents/{doc_a}/retry', token=token_a)
            assert response.status_code == 202
            repeated = wait_status(token_a, doc_a)
            rows = service_client.table('chunks').select('chunk_index').eq('document_id', doc_a).eq('user_id', owner_a).execute().data
            assert repeated['chunk_count'] == ready['chunk_count'] == len(rows)
            assert sorted(row['chunk_index'] for row in rows) == list(range(len(rows)))
            print('PASS: reprocessing replaces the index without duplicate or missing chunks.', flush=True)

            scanned = upload(token_a, owner_a, 'phase2-scanned.pdf', make_pdf([''], image_only=True))
            failed = wait_status(token_a, scanned, 'failed')
            assert 'OCR' in failed['processing_error']
            assert request('POST', f'/api/documents/{scanned}/retry', token=token_a).status_code == 202
            assert 'OCR' in wait_status(token_a, scanned, 'failed')['processing_error']
            print('PASS: scanned PDF fails with OCR guidance and can be retried safely.', flush=True)
        finally:
            # Cleanup is restricted to IDs created above; original books are untouched.
            for document_id, owner, token in documents:
                try:
                    service_client.storage.from_(settings.books_bucket).remove([f'{owner}/{document_id}.pdf'])
                    service_client.table('documents').delete().eq('id', document_id).eq('user_id', owner).execute()
                except Exception as exc:
                    print('Temporary document cleanup needs attention:', document_id, type(exc).__name__, flush=True)
            for owner in users:
                response = client.delete(auth_url + '/admin/users/' + owner, headers=admin)
                if response.status_code not in (200, 204):
                    print('Temporary account cleanup needs attention:', owner, response.status_code, flush=True)
            print('Temporary test accounts and PDFs cleanup completed.', flush=True)


if __name__ == '__main__':
    run()

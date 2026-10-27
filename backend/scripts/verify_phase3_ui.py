"""Browser checks for chat, citations, retry, history, and mobile layout.

PHASE3_LIVE_TEST=1 uses a temporary confirmed auth account (no email is sent).
PHASE3_UI_FIXTURES=1 additionally replaces only the book/chat API with fixtures;
this can verify the interface before migration/model setup. Without that flag,
the same checks upload and ask questions through the real API and local model.
"""

import json
import os
import re
import secrets
import sys
import time
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from app.config import settings
from app.supabase_client import service_client
from tests.pdf_factory import FACT_PAGES, make_pdf


def fixture_api(page, state):
    """Deterministic browser fixtures explicitly separate UI tests from live RAG."""
    document, conversations, histories, turns = state['book'], {}, {}, {}
    now = '2026-10-27T00:00:00Z'
    def handler(route):
        request = route.request
        path = request.url.split('/api/', 1)[1].split('?', 1)[0]
        method = request.method
        payload = None; status = 200
        if method == 'OPTIONS':
            payload = {}
        elif path == 'documents': payload = [document]
        elif path == f"documents/{document['id']}": payload = document
        elif path.endswith('/conversations'): payload = list(reversed(list(conversations.values())))
        elif path.endswith('/ask'):
            body = request.post_data_json
            state['request_ids'].append(body['request_id'])
            if state.get('fail_next'):
                state['fail_next'] = False; payload = {'detail': 'Temporary fixture failure. Please retry.'}; status = 503
            elif body['request_id'] in turns: payload = turns[body['request_id']]
            else:
                conversation = body.get('conversation_id') or str(uuid4())
                if conversation not in conversations:
                    conversations[conversation] = {'id': conversation, 'document_id': document['id'], 'title': body['question'], 'created_at': now, 'updated_at': now}
                    histories[conversation] = []
                question = body['question']; title = 'title' in question.lower(); unsupported = 'cryptocurrency' in question.lower()
                markup = 'literal markup' in question.lower()
                text = '<img src=x onerror="window.__bookwiseInjected=true"> is literal book text.' if markup else "I couldn't find enough evidence in this book to answer that question." if unsupported else 'The title is Field Notes.' if title else 'Plants release oxygen as a byproduct.'
                quote = 'Field Notes' if title else 'Plants release oxygen as a byproduct.'
                if markup: quote = text
                citations = [] if unsupported else [{'rank': 1, 'source_kind': 'metadata' if title else 'passage', 'chunk_id': None if title else str(uuid4()), 'document_id': document['id'], 'filename': document['filename'], 'page_start': None if title else 3, 'page_end': None if title else 3, 'quote': quote, 'excerpt': 'PDF title: Field Notes' if title else FACT_PAGES[2]}]
                if markup: citations[0]['excerpt'] = text
                answer = {'status': 'insufficient_evidence' if unsupported else 'answered', 'method': 'metadata' if title else 'model', 'content': text + ('' if unsupported else ' [1]'), 'statements': [] if unsupported else [{'text': text, 'citation_ranks': [1]}], 'citations': citations}
                payload = {'conversation_id': conversation, 'request_id': body['request_id'], 'user_message_id': str(uuid4()), 'message_id': str(uuid4()), 'document_id': document['id'], 'question': question, 'created_at': now, 'answer': answer}
                messages = histories[conversation]; sequence = len(messages) + 1
                messages.extend([{'id': payload['user_message_id'], 'role': 'user', 'content': question, 'sequence_number': sequence, 'created_at': now, 'answer_payload': None}, {'id': payload['message_id'], 'role': 'assistant', 'content': answer['content'], 'sequence_number': sequence + 1, 'created_at': now, 'answer_payload': answer}])
                turns[body['request_id']] = payload
        elif path.startswith('conversations/'):
            conversation = path.split('/')[1]
            if method == 'DELETE':
                conversations.pop(conversation, None); histories.pop(conversation, None); status = 204
            else: payload = {'conversation': conversations[conversation], 'messages': histories[conversation], 'earlier_messages_available': False, 'oldest_sequence': 1}
        else: payload = {'detail': 'Unknown fixture route'}; status = 404
        headers = {'Access-Control-Allow-Origin': os.environ.get('PHASE3_TEST_FRONTEND_URL', 'http://localhost:3000').rstrip('/'), 'Access-Control-Allow-Headers': 'Authorization,Content-Type', 'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS'}
        route.fulfill(status=status, content_type='application/json', headers=headers, body='' if status == 204 else json.dumps(payload))
    page.route('http://127.0.0.1:8000/api/**', handler)


def run():
    if os.environ.get('PHASE3_LIVE_TEST') != '1':
        raise SystemExit('Set PHASE3_LIVE_TEST=1 to test with a temporary confirmed account.')
    fixtures = os.environ.get('PHASE3_UI_FIXTURES') == '1'
    frontend = os.environ.get('PHASE3_TEST_FRONTEND_URL', 'http://localhost:3000').rstrip('/')
    base = settings.supabase_url.rstrip('/')
    admin = {'apikey': settings.supabase_secret_key, 'Authorization': f'Bearer {settings.supabase_secret_key}'}
    owner = None
    with httpx.Client(timeout=240) as client:
        try:
            email, password = f'phase3-ui-{uuid4().hex}@example.com', secrets.token_urlsafe(28)
            response = client.post(base + '/auth/v1/admin/users', headers=admin, json={'email': email, 'password': password, 'email_confirm': True})
            response.raise_for_status(); owner = response.json()['id']
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else 'chromium', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page(); page_errors = []
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                state = {'request_ids': [], 'book': {'id': str(uuid4()), 'filename': 'phase3-browser-evidence.pdf', 'title': 'Field Notes', 'author': 'Ada Reader', 'status': 'ready', 'page_count': 4, 'chunk_count': 4, 'created_at': '2026-10-27T00:00:00Z', 'processing_error': None, 'processing_stage': None, 'processed_at': None}}
                if fixtures: fixture_api(page, state)
                page.goto(frontend + '/login', wait_until='networkidle')
                if os.environ.get('PHASE4_PRODUCTION_BROWSER') == '1':
                    policy = page.request.get(frontend + '/login').headers['content-security-policy']
                    assert "'unsafe-eval'" not in policy
                page.get_by_label('Email address', exact=True).fill(email)
                page.get_by_label('Password', exact=True).fill(password)
                page.get_by_role('button', name='Sign in', exact=True).click()
                page.wait_for_url('**/library', timeout=30000)
                if os.environ.get('PHASE4_UI') == '1':
                    expect(page.get_by_label('Your usage', exact=True)).to_be_visible(timeout=15000)
                if os.environ.get('PHASE4_PRODUCTION_BROWSER') == '1':
                    auth_cookies = [cookie for cookie in context.cookies() if cookie['name'].startswith('sb-')]
                    assert auth_cookies and all(cookie['secure'] and cookie['sameSite'] == 'Lax' for cookie in auth_cookies)
                    print('PASS: production auth cookies are Secure and SameSite=Lax.', flush=True)
                if not fixtures:
                    page.locator('input[type=file]').set_input_files({'name': state['book']['filename'], 'mimeType': 'application/pdf', 'buffer': make_pdf([text * 6 for text in FACT_PAGES], metadata={'/Title': 'Field Notes', '/Author': 'Ada Reader'})})
                row = page.locator('article.book-row').filter(has_text=state['book']['filename'])
                expect(row.get_by_text('ready', exact=True)).to_be_visible(timeout=120000)
                row.get_by_role('link', name='Ask book', exact=True).click()
                expect(page.get_by_role('heading', name='Field Notes', exact=True)).to_be_visible(timeout=30000)
                question = page.get_by_label('Ask this book', exact=True)
                ask_button = page.get_by_role('button', name='Ask book', exact=True)
                question.fill('What is the title?'); ask_button.click()
                expect(page.locator('.chat-assistant').last).to_contain_text('The title is Field Notes.', timeout=30000)
                page.get_by_role('button', name='Open source 1', exact=True).last.click()
                expect(page.locator('details.chat-source').last).to_have_attribute('open', '')
                expect(page.locator('details.chat-source').last).to_contain_text('PDF metadata')
                print('PASS: protected chat route, title answer, citation button, and expandable metadata source.', flush=True)

                question.fill('Which gas do plants release during photosynthesis?'); ask_button.click()
                expect(page.locator('.chat-assistant')).to_have_count(2, timeout=240000)
                expect(page.locator('.chat-assistant').last).to_contain_text('oxygen', timeout=2000)
                labels = page.locator('.chat-assistant').last.locator('.chat-source summary').all_text_contents()
                ranges = [re.search(r'Pages? (\d+)(?:–(\d+))?', label) for label in labels]
                assert any(match and int(match[1]) <= 3 <= int(match[2] or match[1]) for match in ranges), labels
                question.fill('Who invented cryptocurrency?'); ask_button.click()
                expect(page.locator('.chat-insufficient')).to_contain_text("couldn't find enough evidence", timeout=30000)
                expect(page.locator('.chat-insufficient .chat-source')).to_have_count(0)
                page.reload(wait_until='networkidle')
                expect(page.locator('.chat-assistant')).to_have_count(3, timeout=30000)
                expect(page.locator('.chat-assistant').nth(1)).to_contain_text('oxygen')
                print('PASS: cited answer, insufficient evidence, and persisted conversation after reload.', flush=True)

                if fixtures:
                    state['fail_next'] = True
                    question.fill('Which gas do plants release?'); ask_button.click()
                    expect(page.get_by_role('button', name='Retry answer', exact=True)).to_be_visible(timeout=10000)
                    page.get_by_role('button', name='Retry answer', exact=True).click()
                    expect(page.locator('.chat-assistant')).to_have_count(4, timeout=15000)
                    assert state['request_ids'][-1] == state['request_ids'][-2]
                    print('PASS: failed answer can retry with the same idempotency key and one visible turn.', flush=True)
                    question.fill('Show literal markup from the book'); ask_button.click()
                    expect(page.locator('.chat-assistant')).to_have_count(5, timeout=15000)
                    expect(page.locator('.chat-assistant').last).to_contain_text('<img src=x')
                    assert page.locator('.chat-assistant').last.locator('img').count() == 0
                    assert page.evaluate('window.__bookwiseInjected === undefined')
                    print('PASS: untrusted answer/source markup is rendered literally and cannot execute.', flush=True)

                page.screenshot(path='.cache/phase3-browser-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                page.screenshot(path='.cache/phase3-browser-mobile.png', full_page=True)
                page.get_by_role('button', name='New conversation', exact=True).click()
                expect(page.locator('.chat-assistant')).to_have_count(0)
                page.get_by_label('Conversation', exact=True).select_option(index=1)
                expect(page.locator('.chat-assistant')).to_have_count(5 if fixtures else 3, timeout=15000)
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='Delete conversation', exact=True).click()
                expect(page.locator('.chat-assistant')).to_have_count(0, timeout=15000)
                if os.environ.get('PHASE4_UI') == '1' and not fixtures:
                    page.goto(frontend + '/library', wait_until='networkidle')
                    expect(page.get_by_label('Your usage', exact=True)).to_contain_text('3/' + str(settings.questions_per_day), timeout=15000)
                    row = page.locator('article.book-row').filter(has_text=state['book']['filename'])
                    page.once('dialog', lambda dialog: dialog.accept())
                    row.get_by_role('button', name='Delete', exact=False).click()
                    expect(row).to_have_count(0, timeout=15000)
                    print('PASS: private usage summary reflects question requests; deleting a book removes it from the library.', flush=True)
                assert not page_errors, '; '.join(page_errors)
                print('PASS: desktop/mobile fit, new/resume/delete conversation, and no JavaScript errors.', flush=True)
                print('UI API mode: ' + ('fixtures (not a live RAG result)' if fixtures else 'live database and model'), flush=True)
                context.close(); browser.close()
        finally:
            if owner:
                rows = service_client.table('documents').select('id,storage_key').eq('user_id', owner).execute().data or []
                for row in rows:
                    service_client.storage.from_(settings.books_bucket).remove([row['storage_key']])
                    service_client.table('documents').delete().eq('id', row['id']).eq('user_id', owner).execute()
                response = client.delete(base + '/auth/v1/admin/users/' + owner, headers=admin)
                response.raise_for_status()
            print('Temporary browser account and PDFs removed.', flush=True)


if __name__ == '__main__':
    run()

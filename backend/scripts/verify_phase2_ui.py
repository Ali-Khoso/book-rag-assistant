"""Opt-in browser check: login, upload, processing, search, retry, and deletion.

Run from backend with PHASE2_LIVE_TEST=1. Uses an isolated headless browser and
one temporary, auto-confirmed account; never sends email or uses a real password.
"""

import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from app.config import settings
from app.supabase_client import service_client
from tests.pdf_factory import FACT_PAGES, make_pdf


def run() -> None:
    if os.environ.get('PHASE2_LIVE_TEST') != '1':
        raise SystemExit('Set PHASE2_LIVE_TEST=1 to run browser checks with a temporary account.')
    auth_url = settings.supabase_url.rstrip('/') + '/auth/v1'
    admin = {'apikey': settings.supabase_secret_key, 'Authorization': f'Bearer {settings.supabase_secret_key}'}
    frontend_url = os.environ.get('PHASE2_TEST_FRONTEND_URL', 'http://localhost:3000')
    owner = None
    with httpx.Client(timeout=30, http2=False) as client:
        try:
            email = f'phase2-test-ui-{uuid4().hex}@example.com'
            password = secrets.token_urlsafe(28)
            response = client.post(auth_url + '/admin/users', headers=admin,
                json={'email': email, 'password': password, 'email_confirm': True})
            response.raise_for_status()
            owner = response.json()['id']
            with sync_playwright() as playwright:
                channel = os.environ.get('PHASE2_BROWSER_CHANNEL', 'msedge' if sys.platform == 'win32' else 'chromium')
                browser = playwright.chromium.launch(channel=channel, headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                page_errors = []
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                page.goto(frontend_url + '/login', wait_until='networkidle')

                # Authentication messages and the existing password eye stay usable.
                page.get_by_role('button', name='Sign in', exact=True).click()
                expect(page.locator('#auth-error')).to_contain_text('Check your details')
                page.get_by_label('Email address', exact=True).fill(email)
                page.get_by_label('Password', exact=True).fill(password)
                page.get_by_role('button', name='Show password', exact=True).click()
                expect(page.get_by_label('Password', exact=True)).to_have_attribute('type', 'text')
                page.get_by_role('button', name='Hide password', exact=True).click()
                expect(page.get_by_label('Password', exact=True)).to_have_attribute('type', 'password')
                page.get_by_role('button', name='Sign in', exact=True).click()
                page.wait_for_url('**/library', timeout=30000)
                expect(page.get_by_text('Your shelf is waiting')).to_be_visible(timeout=20000)

                # PDF text extraction -> text chunking -> embeddings via the real UI.
                filename = 'phase2-browser-evidence.pdf'
                page.locator('input[type=file]').set_input_files({'name': filename,
                    'mimeType': 'application/pdf', 'buffer': make_pdf([text * 8 for text in FACT_PAGES])})
                row = page.locator('article.book-row').filter(has_text=filename)
                expect(row).to_be_visible(timeout=20000)
                expect(row.get_by_text('ready', exact=True)).to_be_visible(timeout=120000)
                expect(row).to_contain_text('4 pages')
                row.get_by_role('button', name='Search book', exact=True).click()
                page.get_by_label('What would you like to find?').fill('Which gas do plants release during photosynthesis?')
                page.get_by_role('button', name='Search this book', exact=True).click()
                cards = page.locator('.passage-card')
                expect(cards.first).to_be_visible(timeout=30000)
                expect(cards.first).to_contain_text('oxygen')
                print('PASS: browser sign-in, PDF upload, automatic processing, and source passage search.', flush=True)

                # Check the real responsive layout, not just TypeScript compilation.
                page.screenshot(path='.cache/phase2-browser-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                page.screenshot(path='.cache/phase2-browser-mobile.png', full_page=True)
                print('PASS: desktop and mobile search layouts fit the viewport.', flush=True)

                # Processing status and retry: retain one indexed copy after reprocess.
                with page.expect_response(lambda response: response.url.endswith('/retry') and response.request.method == 'POST') as retry_response:
                    row.get_by_role('button', name='Reprocess', exact=True).click()
                assert retry_response.value.status == 202
                expect(row.get_by_text('ready', exact=True)).not_to_be_visible(timeout=10000)
                expect(row.get_by_text('ready', exact=True)).to_be_visible(timeout=120000)
                page.once('dialog', lambda dialog: dialog.accept())
                row.get_by_role('button', name='Delete', exact=False).click()
                expect(row).to_have_count(0, timeout=20000)
                assert not page_errors, 'Unexpected browser error: ' + '; '.join(page_errors)
                print('PASS: browser reprocessing and deletion; no JavaScript page errors.', flush=True)
                context.close()
                browser.close()
        finally:
            if owner:
                rows = service_client.table('documents').select('id,storage_key').eq('user_id', owner).execute().data or []
                for row in rows:
                    service_client.storage.from_(settings.books_bucket).remove([row['storage_key']])
                    service_client.table('documents').delete().eq('id', row['id']).eq('user_id', owner).execute()
                response = client.delete(auth_url + '/admin/users/' + owner, headers=admin)
                response.raise_for_status()
            print('Temporary browser account and files removed.', flush=True)


if __name__ == '__main__':
    run()

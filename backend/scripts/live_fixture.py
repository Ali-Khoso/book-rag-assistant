"""Temporary confirmed accounts for opt-in verification; no email is sent."""

import secrets
import time
from uuid import uuid4

import httpx

from app.config import settings
from app.supabase_client import service_client


class LiveFixture:
    def __init__(self, api):
        self.api = api.rstrip('/')
        self.base = settings.supabase_url.rstrip('/')
        self.admin = {'apikey': settings.supabase_secret_key, 'Authorization': f'Bearer {settings.supabase_secret_key}'}
        self.public = {'apikey': settings.supabase_publishable_key}
        self.accounts = []
        self.client = httpx.Client(timeout=300)

    def __enter__(self): return self

    def user(self):
        email, password = f'phase4-test-{uuid4().hex}@example.com', secrets.token_urlsafe(28)
        response = self.client.post(self.base + '/auth/v1/admin/users', headers=self.admin,
            json={'email': email, 'password': password, 'email_confirm': True})
        response.raise_for_status()
        owner = response.json()['id']; self.accounts.append(owner)
        session = self.client.post(self.base + '/auth/v1/token?grant_type=password', headers=self.public,
            json={'email': email, 'password': password})
        session.raise_for_status()
        return {'id': owner, 'token': session.json()['access_token']}

    def request(self, method, path, user=None, **kwargs):
        return self.client.request(method, self.api + path,
            headers={'Authorization': 'Bearer ' + user['token']} if user else {}, **kwargs)

    def wait_ready(self, user, document):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = self.request('GET', '/api/documents/' + document, user)
            response.raise_for_status(); book = response.json()
            if book['status'] == 'ready': return book
            if book['status'] == 'failed': raise AssertionError('Synthetic PDF failed: ' + str(book.get('processing_error')))
            time.sleep(1)
        raise AssertionError('Standalone worker did not finish the synthetic book')

    def wait_purged(self, document):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if not service_client.table('documents').select('id').eq('id', document).execute().data: return
            time.sleep(1)
        raise AssertionError('Worker did not purge the temporary document')

    def __exit__(self, *_):
        failures = []
        for owner in self.accounts:
            try:
                rows = service_client.table('documents').select('id,storage_key').eq('user_id', owner).execute().data or []
                for row in rows:
                    service_client.storage.from_(settings.books_bucket).remove([row['storage_key']])
                    service_client.table('documents').delete().eq('id', row['id']).eq('user_id', owner).execute()
                response = self.client.delete(self.base + '/auth/v1/admin/users/' + owner, headers=self.admin)
                response.raise_for_status()
            except Exception:
                failures.append(owner)
        self.client.close()
        if failures:
            raise RuntimeError('Temporary account cleanup needs attention for IDs: ' + ','.join(failures))
        print('Temporary Phase 4 accounts and PDFs removed.', flush=True)


def clear_budget(owner, action, period):
    """Only a synthetic account created by the caller may be supplied here."""
    service_client.table('usage_windows').delete().eq('user_id', owner).eq('action', action).eq('period', period).execute()

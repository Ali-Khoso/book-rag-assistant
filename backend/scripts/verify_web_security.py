"""Check actual production HTML headers/nonces and authenticated browser behavior."""

import os
import re
from html.parser import HTMLParser

import httpx


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script': self.scripts.append(dict(attrs))


def run():
    origin = os.environ.get('PHASE3_TEST_FRONTEND_URL', 'http://localhost:3001').rstrip('/')
    with httpx.Client(timeout=20) as client:
        first = client.get(origin + '/login'); second = client.get(origin + '/login')
        first.raise_for_status(); second.raise_for_status()
        policy = first.headers['content-security-policy']
        nonce = re.search(r"'nonce-([^']+)'", policy)[1]
        assert nonce != re.search(r"'nonce-([^']+)'", second.headers['content-security-policy'])[1]
        scripts = Scripts(); scripts.feed(first.text)
        executable = [script for script in scripts.scripts if script.get('type') not in ('application/json','application/ld+json')]
        assert executable and all(script.get('nonce') == nonce for script in executable)
        script_policy = next(part for part in policy.split(';') if part.strip().startswith('script-src'))
        assert "'unsafe-inline'" not in script_policy and "'unsafe-eval'" not in script_policy
        assert first.headers['x-frame-options'] == 'DENY' and first.headers['x-content-type-options'] == 'nosniff'
        assert 'no-store' in first.headers['cache-control']
        assert first.headers.get('x-powered-by') is None
    print('PASS: production HTML has fresh matching script nonces, no unsafe script policy, and private security headers.', flush=True)
    os.environ['PHASE3_TEST_FRONTEND_URL'] = origin
    os.environ['PHASE3_UI_FIXTURES'] = '1'
    os.environ['PHASE4_PRODUCTION_BROWSER'] = '1'
    from scripts.verify_phase3_ui import run as verify_browser
    verify_browser()


if __name__ == '__main__': run()

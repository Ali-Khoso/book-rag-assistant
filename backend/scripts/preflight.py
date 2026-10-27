"""Validate production configuration and optionally probe deployed HTTPS services."""

import argparse
from urllib.parse import urlsplit

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--frontend-url', required=True)
    parser.add_argument('--check-live', action='store_true')
    args = parser.parse_args()
    from app.config import settings
    assert settings.environment == 'production', 'Use production settings via BOOKWISE_ENV_FILE or environment variables.'
    api, frontend = urlsplit(args.api_url), urlsplit(args.frontend_url)
    assert api.scheme == frontend.scheme == 'https', 'Both public origins must use HTTPS.'
    assert api.hostname in settings.allowed_hosts, 'ALLOWED_HOSTS must include the backend hostname.'
    assert args.frontend_url.rstrip('/') == settings.frontend_origin, 'FRONTEND_ORIGIN must match the actual Vercel production origin.'
    assert api.hostname not in ('localhost','127.0.0.1'), 'A deployed browser cannot call your development computer.'
    print('PASS: production origins, host allowlist, and required controls.', flush=True)
    if args.check_live:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for path in ('/api/live','/api/ready'):
                response = client.get(args.api_url.rstrip('/') + path)
                response.raise_for_status()
            response = client.get(args.api_url.rstrip('/') + '/api/health')
            response.raise_for_status(); assert response.json()['phase'] == '4'
            page = client.get(args.frontend_url.rstrip('/') + '/login')
            page.raise_for_status()
            assert 'nonce-' in page.headers.get('Content-Security-Policy','')
            assert 'no-store' in page.headers.get('Cache-Control','')
            cors = client.options(args.api_url.rstrip('/') + '/api/documents', headers={
                'Origin':args.frontend_url.rstrip('/'), 'Access-Control-Request-Method':'GET',
                'Access-Control-Request-Headers':'Authorization'})
            cors.raise_for_status()
            assert cors.headers.get('Access-Control-Allow-Origin') == args.frontend_url.rstrip('/')
        print('PASS: deployed readiness, production frontend policy, and exact-origin API access.', flush=True)


if __name__ == '__main__': main()

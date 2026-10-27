"""HTTP hardening: bounded streaming bodies, request correlation, and safe logs."""

from time import monotonic
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.observability import event, metrics, request_id


class OperationalMiddleware:
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        correlation = str(uuid4())
        context = request_id.set(correlation)
        started = monotonic()
        method = scope['method'] if scope['method'] in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS') else 'OTHER'
        status = 500
        size = 0
        upload = scope['method'] == 'POST' and scope['path'] == '/api/documents'
        limit = self.config.max_pdf_size_bytes + 1024 * 1024 if upload else self.config.max_json_body_bytes

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message['type'] == 'http.request':
                size += len(message.get('body', b''))
                if size > limit:
                    raise HTTPException(413, 'The request is too large.')
            return message

        async def secured_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = list(message.get('headers', [])) + [
                    (b'x-request-id', correlation.encode()), (b'x-content-type-options', b'nosniff'),
                    (b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer')]
            await send(message)

        try:
            headers = dict(scope.get('headers', []))
            length = headers.get(b'content-length')
            if length:
                try:
                    declared = int(length)
                except ValueError:
                    return await JSONResponse({'detail': 'Invalid request size.'}, 400)(scope, receive, secured_send)
                if declared < 0:
                    return await JSONResponse({'detail': 'Invalid request size.'}, 400)(scope, receive, secured_send)
                if declared > limit:
                    return await JSONResponse({'detail': 'The request is too large.'}, 413)(scope, receive, secured_send)
            await self.app(scope, bounded_receive, secured_send)
        finally:
            elapsed = monotonic() - started
            route = getattr(scope.get('route'), 'path', 'unmatched')
            metrics.request(method, route, status, elapsed)
            event('http_request', method=method, route=route, status=status, duration_ms=round(elapsed * 1000))
            request_id.reset(context)

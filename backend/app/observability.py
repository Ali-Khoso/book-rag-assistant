"""Privacy-preserving JSON logs and bounded per-process operational counters."""

import json
import logging
from collections import Counter
from contextvars import ContextVar
from threading import Lock

request_id = ContextVar('request_id', default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Deliberately omit exception bodies, headers, prompts, and document text.
        row = {'level': record.levelname, 'logger': record.name,
            'event': getattr(record, 'event', 'application'), 'message': record.getMessage()}
        fields = getattr(record, 'fields', {})
        row.update(fields)
        if request_id.get():
            row['request_id'] = request_id.get()
        return json.dumps(row, ensure_ascii=True)


def configure_logging():
    root = logging.getLogger('app')
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.propagate = False
    root.setLevel(logging.INFO)


def event(name, **fields):
    logging.getLogger('app.operations').info(name, extra={'event': name, 'fields': fields})


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._requests = Counter()
        self._models = Counter()
        self._duration = 0.0

    def request(self, method, route, status, elapsed):
        with self._lock:
            self._requests[(method, route, str(status))] += 1
            self._duration += elapsed

    def model(self, provider, success, elapsed, input_tokens=0, output_tokens=0):
        with self._lock:
            self._models[(provider, 'success' if success else 'error')] += 1
            self._models[(provider, 'input_tokens')] += input_tokens or 0
            self._models[(provider, 'output_tokens')] += output_tokens or 0
        event('model_call', provider=provider, success=success, duration_ms=round(elapsed * 1000),
            input_tokens=input_tokens, output_tokens=output_tokens)

    def snapshot(self):
        with self._lock:
            return {'requests': [{'method': key[0], 'route': key[1], 'status': key[2], 'count': count}
                for key, count in self._requests.items()], 'request_duration_seconds': round(self._duration, 3),
                'models': [{'provider': key[0], 'measure': key[1], 'value': value} for key, value in self._models.items()]}


metrics = Metrics()

"""Readiness probes check shared services without generating paid model output."""

from threading import Lock
from time import monotonic

import httpx


class Readiness:
    def __init__(self, controls, embeddings, config):
        self.controls, self.embeddings, self.config = controls, embeddings, config
        self._lock = Lock()
        self._checked = 0
        self._result = {'database': False, 'worker': False, 'embeddings': False, 'answers': False}

    def check(self):
        with self._lock:
            if monotonic() - self._checked < 3:
                return self._result.copy()
            result = {key: False for key in self._result}
            try:
                health = self.controls.health()
                result['database'], result['worker'] = bool(health['database']), bool(health['worker'])
            except Exception:
                pass
            try:
                self.embeddings.warmup()
                result['embeddings'] = True
            except Exception:
                pass
            try:
                if self.config.llm_provider == 'ollama':
                    response = httpx.get(self.config.ollama_url.rstrip('/') + '/api/tags', timeout=3)
                    response.raise_for_status()
                    wanted = self.config.llm_model
                    names = [row['name'] for row in response.json()['models']]
                    result['answers'] = wanted in names or wanted + ':latest' in names
                else:
                    # Hosted credentials are validated by settings; a paid generation
                    # request must never be part of a recurring health probe.
                    result['answers'] = bool(self.config.openai_api_key)
            except Exception:
                pass
            self._result, self._checked = result, monotonic()
            return result.copy()

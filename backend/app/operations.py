"""Operational controls: persistent per-user budgets and private usage summaries."""

from datetime import datetime, timezone


class LimitExceeded(Exception):
    def __init__(self, retry_after: int, action: str):
        self.retry_after = max(1, int(retry_after))
        label = 'Question' if action == 'ask' else 'Request'
        super().__init__(f'{label} limit reached. Try again in {self.retry_after} seconds.')


class LibraryQuotaExceeded(Exception):
    """A durable library reservation would exceed the owner's storage budget."""


class ControlsUnavailable(Exception):
    """Limits fail closed when their shared database cannot be reached."""


class OperationalControls:
    def __init__(self, client, config):
        self.client, self.config = client, config

    def consume(self, owner: str, action: str, operation_id=None):
        if not self.config.limits_enabled:
            return
        limits = {
            'read': (self.config.read_requests_per_minute, 10000),
            'upload': (self.config.upload_requests_per_minute, self.config.uploads_per_day),
            'search': (self.config.search_requests_per_minute, 1000),
            'ask': (self.config.ask_requests_per_minute, self.config.questions_per_day),
            'retry': (5, 30), 'delete': (20, 1000),
        }
        minute, daily = limits[action]
        try:
            result = self.client.rpc('phase4_consume_usage', {'p_user_id': owner, 'p_action': action,
                'p_minute_limit': minute, 'p_daily_limit': daily,
                'p_operation_id': str(operation_id) if operation_id else None}).execute().data
            allowed, retry_after = result['allowed'], result['retry_after']
        except Exception as exc:
            raise ControlsUnavailable('Usage checks are temporarily unavailable. Please try again.') from exc
        if not allowed:
            raise LimitExceeded(retry_after, action)

    def usage(self, owner: str):
        """Return only the verified owner's usage, including pending storage cleanup."""
        rows = self.client.table('documents').select('file_size_bytes,status').eq('user_id', owner).execute().data or []
        day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        windows = self.client.table('usage_windows').select('request_count').eq('user_id', owner).eq('action', 'ask')\
            .eq('period', 'day').gte('window_start', day).execute().data or []
        return {'books': len(rows), 'max_books': self.config.max_books_per_user,
            'storage_bytes': sum(row['file_size_bytes'] for row in rows), 'max_storage_bytes': self.config.max_storage_bytes_per_user,
            'questions_today': sum(row['request_count'] for row in windows), 'max_questions_per_day': self.config.questions_per_day,
            'pending_deletions': sum(row['status'] == 'deleting' for row in rows)}

    def health(self):
        return self.client.rpc('phase4_health', {}).execute().data

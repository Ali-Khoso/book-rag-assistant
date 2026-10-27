"""Processing status and retry: poll durable queued rows outside upload requests."""

import logging
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from app.processing.pipeline import process_document

logger = logging.getLogger(__name__)


class ProcessingWorker:
    """A local background worker; Postgres claims prevent duplicate processing."""

    def __init__(self, repository, embeddings, config):
        self.repository = repository
        self.embeddings = embeddings
        self.config = config
        self._stop = Event()
        self._wake = Event()
        self._thread = None
        self.state = "stopped"
        self.worker_id = str(uuid4())
        self._heartbeat_thread = None
        self._last_housekeeping = 0

    def start(self) -> None:
        self._start_heartbeat()
        self._thread = Thread(target=self._run, name="book-processing", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        try:
            self.repository.heartbeat(self.worker_id, 'stopped')
        except Exception:
            pass

    def run_forever(self):
        """Standalone deployment entry point; API processes need no worker threads."""
        self._start_heartbeat()
        try:
            self._run()
        finally:
            self.stop()

    def _start_heartbeat(self):
        self.state = 'idle'
        self._heartbeat_thread = Thread(target=self._heartbeat, name='worker-heartbeat', daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat(self):
        """A separate lightweight heartbeat stays fresh during long PDF extraction."""
        while not self._stop.is_set():
            try:
                self.repository.heartbeat(self.worker_id, self.state)
            except Exception:
                pass
            self._stop.wait(self.config.worker_heartbeat_seconds)

    def process_once(self):
        """Prioritize private file cleanup, then claim one durable ingestion job."""
        cleanup = self.repository.claim_deletion()
        if cleanup:
            self.state = 'processing'
            if not self.repository.clean_deletion(cleanup):
                logger.warning('Private file cleanup deferred; inspect authenticated operational metrics.')
            return True
        job = self.repository.claim_next(self.embeddings.model_id)
        if job:
            self.state = 'processing'
            process_document(job, self.repository, self.embeddings, self.config)
            return True
        self.state = 'idle'
        return False

    def _run(self) -> None:
        """Existing queued books are picked up automatically after API startup."""
        reported_error = False
        while not self._stop.is_set():
            try:
                if monotonic() - self._last_housekeeping > 3600:
                    self.repository.housekeeping()
                    self._last_housekeeping = monotonic()
                worked = self.process_once()
                reported_error = False
                if worked:
                    continue
            except Exception:
                self.state = "waiting_for_database"
                if not reported_error:
                    logger.warning("Processing queue unavailable. Check database connectivity and migration 0005_phase4_operations.sql.")
                    reported_error = True
            self._wake.wait(self.config.processing_poll_seconds)
            self._wake.clear()
        self.state = "stopped"

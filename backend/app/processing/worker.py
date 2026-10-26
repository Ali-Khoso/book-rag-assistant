"""Processing status and retry: poll durable queued rows outside upload requests."""

import logging
from threading import Event, Thread

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

    def start(self) -> None:
        self._thread = Thread(target=self._run, name="book-processing", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Existing queued books are picked up automatically after API startup."""
        reported_error = False
        while not self._stop.is_set():
            try:
                job = self.repository.claim_next(self.embeddings.model_id)
                reported_error = False
                if job:
                    self.state = "processing"
                    process_document(job, self.repository, self.embeddings, self.config)
                    continue
                self.state = "idle"
            except Exception:
                self.state = "waiting_for_database"
                if not reported_error:
                    logger.warning("Processing queue unavailable. Check Supabase connectivity and migration 0003_phase2_retrieval.sql.")
                    reported_error = True
            self._wake.wait(self.config.processing_poll_seconds)
            self._wake.clear()
        self.state = "stopped"

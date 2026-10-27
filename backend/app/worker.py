"""Standalone worker: durable ingestion, cleanup recovery, and graceful shutdown."""

import argparse
import signal
from uuid import UUID

from app.config import settings
from app.observability import configure_logging
from app.operations import OperationalControls
from app.processing.embeddings import EmbeddingService
from app.processing.worker import ProcessingWorker
from app.repository import SupabaseRepository
from app.supabase_client import service_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Process at most one cleanup/job, then exit')
    parser.add_argument('--check', action='store_true', help='Check the shared worker heartbeat')
    parser.add_argument('--retry-cleanup', type=UUID, help='Reset a blocked deletion for this exact document')
    args = parser.parse_args()
    configure_logging()
    if args.check:
        healthy = OperationalControls(service_client, settings).health()['worker']
        raise SystemExit(0 if healthy else 1)
    repository = SupabaseRepository(service_client, settings)
    if args.retry_cleanup and not repository.retry_cleanup(str(args.retry_cleanup)):
        raise SystemExit('No pending deletion with that ID.')
    embeddings = EmbeddingService(settings)
    if settings.warm_models:
        embeddings.warmup()
    worker = ProcessingWorker(repository, embeddings, settings)
    for name in ('SIGTERM', 'SIGINT'):
        signal.signal(getattr(signal, name), lambda *_: worker._stop.set())
    if args.once:
        worker.process_once()
    else:
        worker.run_forever()


if __name__ == '__main__':
    main()

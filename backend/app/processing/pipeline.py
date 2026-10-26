"""Phase 2 pipeline: PDF text extraction -> text chunking -> embeddings -> storage."""

import logging
from dataclasses import asdict

from app.config import Settings
from app.processing.chunking import chunk_pages
from app.processing.errors import LostLease, ProcessingError
from app.processing.pdf import extract_pdf

logger = logging.getLogger(__name__)


def process_document(job: dict, repository, embeddings, config: Settings) -> None:
    """Process one claimed book; every write checks that the run still owns it."""
    def progress(stage: str) -> None:
        if not repository.progress(job, stage):
            raise LostLease()

    try:
        # PDF text extraction: keep physical page numbers for later citations.
        progress("Downloading private PDF")
        content = repository.download(job)
        if len(content) > config.max_pdf_size_bytes:
            raise ProcessingError("This PDF exceeds the configured upload limit. Upload a smaller copy.")
        extracted = extract_pdf(content, max_pages=config.max_pdf_pages,
            max_chars=config.max_extracted_chars,
            progress=lambda page, total: progress(f"Reading pages {page}/{total}"))
        del content

        # Text chunking: overlapping text retains book, owner, page, and position.
        progress("Creating overlapping passages")
        chunks = chunk_pages(extracted.pages, chunk_size=config.chunk_size_chars,
            overlap=config.chunk_overlap_chars, max_chunks=config.max_document_chunks)
        if not chunks:
            raise ProcessingError("This PDF contains no searchable passages. It may need OCR.")

        # Embeddings and vector storage: batch work to bound memory and renew leases.
        for start in range(0, len(chunks), config.embedding_batch_size):
            batch = chunks[start:start + config.embedding_batch_size]
            progress(f"Indexing passages {start + 1}–{start + len(batch)} of {len(chunks)}")
            vectors = embeddings.embed([chunk.content for chunk in batch])
            if len(vectors) != len(batch):
                raise ProcessingError("The embedding model returned an incomplete batch. Please retry.")
            rows = [{**asdict(chunk), "embedding": vector} for chunk, vector in zip(batch, vectors, strict=True)]
            if repository.append_chunks(job, rows) != len(rows):
                raise ProcessingError("Not all passages were saved. Please retry processing.")
        if not repository.finish(job, extracted.page_count, len(chunks)):
            raise LostLease()
    except LostLease:
        # A deleted or superseded book must never be recreated by an old task.
        logger.info("Stopped superseded processing run for document %s", job["id"])
    except Exception as exc:
        message = str(exc) if isinstance(exc, ProcessingError) else "Book processing could not finish. Please retry in a moment."
        logger.warning("Document processing failed: %s (%s)", job["id"], type(exc).__name__)
        try:
            repository.fail(job, message)
        except Exception:
            # If the database is unavailable, the persisted lease allows recovery.
            logger.warning("Could not record failure for document %s; its lease will expire", job["id"])

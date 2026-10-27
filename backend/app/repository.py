"""Vector storage and search: all privileged queries retain verified ownership."""

from uuid import uuid4
from datetime import datetime, timezone

from app.config import Settings
from app.operations import LibraryQuotaExceeded


DOCUMENT_FIELDS = "id,filename,status,page_count,created_at,processing_error,processing_stage,chunk_count,processed_at,title,author,processing_attempts,processing_max_attempts,processing_next_attempt_at,file_size_bytes"


class SupabaseRepository:
    """Persist the processing queue and delegate atomic lease operations to SQL."""

    def __init__(self, client, config: Settings):
        self.client = client
        self.config = config

    def list_documents(self, owner: str) -> list[dict]:
        """Expose processing metadata only for the authenticated library owner."""
        return self.client.table("documents").select(DOCUMENT_FIELDS).eq("user_id", owner).neq('status', 'deleting').eq('upload_completed', True).order("created_at", desc=True).execute().data or []

    def get_document(self, document_id: str, owner: str) -> dict | None:
        """Treat a missing book and another user's book identically."""
        result = self.client.table("documents").select("*").eq("id", document_id).eq("user_id", owner).neq('status', 'deleting').eq('upload_completed', True).maybe_single().execute()
        return result.data if result else None

    def save_metadata(self, document: dict, metadata: dict) -> bool:
        """Cache only PDF-provided metadata, respecting the current index generation."""
        query = self.client.table("documents").update({"title": metadata.get("title"),
            "author": metadata.get("author"), "metadata_checked": True})\
            .eq("id", document["id"]).eq("user_id", document["user_id"])
        if document.get("processing_run_id"):
            query = query.eq("processing_run_id", document["processing_run_id"])
        return bool(query.execute().data)

    def opening_passages(self, document: dict, limit: int = 5) -> list[dict]:
        """Title/author fallbacks inspect opening text instead of semantic guesswork."""
        return self.client.table("chunks").select("id,document_id,content,page_start,page_end,chunk_index")\
            .eq("document_id", document["id"]).eq("user_id", document["user_id"])\
            .eq("processing_run_id", document["processing_run_id"]).order("chunk_index").limit(limit).execute().data or []

    def create_document(self, owner: str, filename: str, content: bytes) -> dict:
        """Store a private upload and its queued row; remove orphan files on failure."""
        document_id = str(uuid4())
        storage_path = f"{owner}/{document_id}.pdf"
        reserved = False
        try:
            self.client.table("users").upsert({"id": owner, "auth_subject": owner}, on_conflict="id").execute()
            reservation = self.client.rpc('phase4_reserve_upload', {'p_user_id': owner, 'p_document_id': document_id,
                'p_filename': filename[:180], 'p_size': len(content), 'p_max_books': self.config.max_books_per_user,
                'p_max_bytes': self.config.max_storage_bytes_per_user,
                'p_max_attempts': self.config.processing_max_attempts}).execute().data
            if not reservation:
                raise RuntimeError('Upload reservation was not returned')
            reserved = True
            self.client.storage.from_(self.config.books_bucket).upload(storage_path, content, {"content-type": "application/pdf", "upsert": "false"})
            complete = self.client.rpc('phase4_complete_upload', {'p_user_id': owner, 'p_document_id': document_id}).execute().data
            if not complete:
                raise RuntimeError('Upload could not be completed')
            return self.get_document(document_id, owner)
        except Exception as exc:
            if reserved:
                try:
                    self.client.rpc('phase4_request_deletion', {'p_user_id': owner, 'p_document_id': document_id}).execute()
                except Exception:
                    # An incomplete reservation expires into cleanup even after a DB outage.
                    pass
            if 'book_quota_exceeded' in str(exc):
                raise LibraryQuotaExceeded('Your library has reached its book limit. Delete a book and allow cleanup to finish.') from exc
            if 'storage_quota_exceeded' in str(exc):
                raise LibraryQuotaExceeded('Your library storage limit is reached. Delete a book and allow cleanup to finish.') from exc
            raise

    def delete_document(self, document: dict, owner: str) -> None:
        """Deleting the owner-scoped row cascades to its chunks and invalidates work."""
        self.client.rpc('phase4_request_deletion', {'p_user_id': owner, 'p_document_id': document['id']}).execute()

    def queue_retry(self, document_id: str, owner: str) -> dict | None:
        """Requeue only inactive jobs; a running claim cannot be replaced by a click."""
        result = self.client.rpc('phase4_queue_retry', {'p_user_id': owner, 'p_document_id': document_id}).execute()
        return result.data[0] if result.data else None

    def claim_next(self, model: str) -> dict | None:
        """Let Postgres atomically assign work across competing worker processes."""
        result = self.client.rpc("phase4_claim_next", {"p_run_id": str(uuid4()), "p_model": model}).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def job_params(job: dict) -> dict:
        return {"p_document_id": job["id"], "p_user_id": job["user_id"], "p_run_id": job["processing_run_id"]}

    def progress(self, job: dict, stage: str) -> bool:
        """Renew the current run's lease; false means this task must stop."""
        return bool(self.client.rpc("phase2_progress", {**self.job_params(job), "p_stage": stage}).execute().data)

    def download(self, job: dict) -> bytes:
        """Read the private original only from its owner's storage folder."""
        if not job["storage_key"].startswith(f"{job['user_id']}/"):
            raise ValueError("Storage ownership mismatch")
        return self.client.storage.from_(self.config.books_bucket).download(job["storage_key"])

    def append_chunks(self, job: dict, chunks: list[dict]) -> int:
        """Commit one embedding batch while the database checks the active lease."""
        return self.client.rpc("phase2_append_chunks", {**self.job_params(job), "p_chunks": chunks}).execute().data

    def finish(self, job: dict, page_count: int, chunk_count: int) -> bool:
        """Make the book searchable only after SQL validates the complete index."""
        return bool(self.client.rpc("phase2_finish", {**self.job_params(job), "p_page_count": page_count,
            "p_expected_chunks": chunk_count}).execute().data)

    def fail(self, job: dict, message: str, *, retryable: bool = False) -> bool:
        """Discard partial chunks and retain a safe message for a later retry."""
        return bool(self.client.rpc("phase4_record_failure", {**self.job_params(job), "p_error": message, 'p_retryable': retryable}).execute().data)

    def claim_deletion(self):
        result = self.client.rpc('phase4_claim_deletion', {'p_claim_id': str(uuid4()),
            'p_max_attempts': self.config.deletion_max_attempts}).execute().data
        return result[0] if result else None

    def clean_deletion(self, document):
        """Remove Storage first, then atomically cascade the leased database row."""
        path = document['storage_key']
        if path != f"{document['user_id']}/{document['id']}.pdf":
            raise ValueError('Storage ownership mismatch')
        params = {'p_user_id': document['user_id'], 'p_document_id': document['id'], 'p_claim_id': document['deletion_claim_id']}
        try:
            self.client.storage.from_(self.config.books_bucket).remove([path])
            return bool(self.client.rpc('phase4_finish_deletion', params).execute().data)
        except Exception:
            self.client.rpc('phase4_fail_deletion', {**params, 'p_max_attempts': self.config.deletion_max_attempts}).execute()
            return False

    def heartbeat(self, worker_id, state):
        self.client.rpc('phase4_heartbeat', {'p_worker_id': worker_id, 'p_state': state}).execute()

    def housekeeping(self):
        self.client.rpc('phase4_housekeeping', {}).execute()

    def retry_cleanup(self, document_id):
        return self.client.table('documents').update({'deletion_attempts': 0, 'deletion_claim_id': None,
            'deletion_claimed_at': None, 'deletion_next_attempt_at': datetime.now(timezone.utc).isoformat(), 'deletion_error': None})\
            .eq('id', document_id).eq('status', 'deleting').execute().data

    def search(self, owner: str, document_id: str, vector: list[float], model: str, limit: int) -> list[dict]:
        """Query one verified owner's book in the matching embedding space."""
        return self.client.rpc("phase2_search", {"p_user_id": owner, "p_document_id": document_id,
            "p_query": vector, "p_model": model, "p_limit": limit}).execute().data or []

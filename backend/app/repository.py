"""Vector storage and search: all privileged queries retain verified ownership."""

from uuid import uuid4

from app.config import Settings


DOCUMENT_FIELDS = "id,filename,status,page_count,created_at,processing_error,processing_stage,chunk_count,processed_at,title,author"


class SupabaseRepository:
    """Persist the processing queue and delegate atomic lease operations to SQL."""

    def __init__(self, client, config: Settings):
        self.client = client
        self.config = config

    def list_documents(self, owner: str) -> list[dict]:
        """Expose processing metadata only for the authenticated library owner."""
        return self.client.table("documents").select(DOCUMENT_FIELDS).eq("user_id", owner).order("created_at", desc=True).execute().data or []

    def get_document(self, document_id: str, owner: str) -> dict | None:
        """Treat a missing book and another user's book identically."""
        result = self.client.table("documents").select("*").eq("id", document_id).eq("user_id", owner).maybe_single().execute()
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
        uploaded = False
        try:
            self.client.table("users").upsert({"id": owner, "auth_subject": owner}, on_conflict="id").execute()
            self.client.storage.from_(self.config.books_bucket).upload(storage_path, content, {"content-type": "application/pdf", "upsert": "false"})
            uploaded = True
            result = self.client.table("documents").insert({"id": document_id, "user_id": owner,
                "filename": filename[:180], "storage_key": storage_path, "status": "queued"}).execute()
            if not result.data:
                raise RuntimeError("Document row was not returned")
            return result.data[0]
        except Exception:
            if uploaded:
                try:
                    self.client.storage.from_(self.config.books_bucket).remove([storage_path])
                except Exception:
                    pass
            raise

    def delete_document(self, document: dict, owner: str) -> None:
        """Deleting the owner-scoped row cascades to its chunks and invalidates work."""
        self.client.storage.from_(self.config.books_bucket).remove([document["storage_key"]])
        self.client.table("documents").delete().eq("id", document["id"]).eq("user_id", owner).execute()

    def queue_retry(self, document_id: str, owner: str) -> dict | None:
        """Requeue only inactive jobs; a running claim cannot be replaced by a click."""
        result = self.client.table("documents").update({"status": "queued", "processing_error": None,
            "processing_stage": "Waiting to process", "processing_run_id": None, "chunk_count": 0})\
            .eq("id", document_id).eq("user_id", owner).in_("status", ["queued", "failed", "ready"]).execute()
        return result.data[0] if result.data else None

    def claim_next(self, model: str) -> dict | None:
        """Let Postgres atomically assign work across competing worker processes."""
        result = self.client.rpc("phase2_claim_next", {"p_run_id": str(uuid4()), "p_model": model}).execute()
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

    def fail(self, job: dict, message: str) -> bool:
        """Discard partial chunks and retain a safe message for a later retry."""
        return bool(self.client.rpc("phase2_fail", {**self.job_params(job), "p_error": message}).execute().data)

    def search(self, owner: str, document_id: str, vector: list[float], model: str, limit: int) -> list[dict]:
        """Query one verified owner's book in the matching embedding space."""
        return self.client.rpc("phase2_search", {"p_user_id": owner, "p_document_id": document_id,
            "p_query": vector, "p_model": model, "p_limit": limit}).execute().data or []

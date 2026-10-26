"""Book API: private uploads, processing status/retry, and source passage retrieval."""

from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, settings
from app.models import DocumentResponse, SearchRequest, SearchResponse
from app.processing.embeddings import EmbeddingService
from app.processing.errors import ProcessingError
from app.processing.worker import ProcessingWorker
from app.repository import SupabaseRepository
from app.security import VerifiedUser, require_user
from app.supabase_client import service_client


def create_app(repository=None, embeddings=None, config: Settings | None = None, *, worker_enabled: bool | None = None) -> FastAPI:
    """Construct the API with replaceable services for offline ownership tests."""
    config = config or settings
    repository = repository or SupabaseRepository(service_client, config)
    embeddings = embeddings or EmbeddingService(config)
    enabled = config.processing_enabled if worker_enabled is None else worker_enabled
    worker = ProcessingWorker(repository, embeddings, config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if enabled:
            worker.start()
        yield
        worker.stop()

    application = FastAPI(title="Book RAG Assistant API", version="0.2.0",
        docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    application.add_middleware(CORSMiddleware,
        allow_origins=[config.frontend_origin], allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"])

    def owned_document(document_id: UUID, user: VerifiedUser) -> dict:
        """Use the verified token's owner before accessing a file, retry, or search."""
        try:
            row = repository.get_document(str(document_id), user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load this book. Please try again.") from exc
        if not row:
            raise HTTPException(status_code=404, detail="Book not found.")
        return row

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "2", "processing": worker.state if enabled else "disabled"}

    @application.get("/api/documents", response_model=list[DocumentResponse])
    def list_documents(user: VerifiedUser = Depends(require_user)):
        """Processing status: return current stages, failures, and indexed counts."""
        try:
            return repository.list_documents(user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load your book library.") from exc

    @application.post("/api/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
    def upload_document(file: UploadFile = File(...), user: VerifiedUser = Depends(require_user)):
        """Validate a private PDF upload, then let the worker process its queued row."""
        filename = PurePosixPath((file.filename or "").replace("\\", "/")).name.strip()
        if not filename or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Choose a PDF file.")
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=415, detail="The uploaded file must have PDF content type.")
        try:
            content = file.file.read(config.max_pdf_size_bytes + 1)
        finally:
            file.file.close()
        if len(content) > config.max_pdf_size_bytes:
            max_mib = config.max_pdf_size_bytes / (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"PDFs must be {max_mib:g} MiB or smaller.")
        if b"%PDF-" not in content[:1024]:
            raise HTTPException(status_code=415, detail="The file does not contain a valid PDF signature.")
        try:
            row = repository.create_document(user.id, filename, content)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="The PDF could not be saved. Please try again.") from exc
        if enabled:
            worker.wake()
        return row

    @application.post("/api/documents/{document_id}/retry", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
    def retry_document(document_id: UUID, user: VerifiedUser = Depends(require_user)):
        """Processing status and retry: safely requeue failed or previously indexed books."""
        row = owned_document(document_id, user)
        if row["status"] == "processing":
            raise HTTPException(status_code=409, detail="This book is already processing. Please wait for it to finish.")
        try:
            queued = repository.queue_retry(str(document_id), user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not queue this book. Please try again.") from exc
        if not queued:
            raise HTTPException(status_code=409, detail="This book has already started processing. Refresh its status.")
        if enabled:
            worker.wake()
        return queued

    @application.post("/api/documents/{document_id}/search", response_model=SearchResponse)
    def search_document(document_id: UUID, request: SearchRequest, user: VerifiedUser = Depends(require_user)):
        """Vector storage and search: retrieve passages only from the owner's ready book."""
        row = owned_document(document_id, user)
        if row["status"] != "ready":
            raise HTTPException(status_code=409, detail="This book is not ready to search. Wait for processing or retry a failed book.")
        if row.get("embedding_model") != embeddings.model_id:
            raise HTTPException(status_code=409, detail="This book needs to be reprocessed before searching. Use Reprocess in your library.")
        try:
            vector = embeddings.embed([request.question])[0]
            passages = repository.search(user.id, str(document_id), vector, embeddings.model_id, request.top_k)
            return {"document_id": document_id, "question": request.question, "passages": passages}
        except ProcessingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not search this book. Please try again.") from exc

    @application.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_document(document_id: UUID, user: VerifiedUser = Depends(require_user)):
        """Remove the private file and owner-scoped row; indexed chunks cascade away."""
        row = owned_document(document_id, user)
        try:
            repository.delete_document(row, user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="The book could not be deleted.")
        return Response(status_code=204)

    return application


app = create_app()

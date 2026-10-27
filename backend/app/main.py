"""Book API: private uploads, retrieval, grounded answers, and conversation history."""

from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from uuid import UUID
from secrets import compare_digest

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from app.config import Settings, settings
from app.answers.llm import LanguageModel, ModelUnavailable
from app.answers.models import AnswerResponse, AskRequest, ConversationResponse, ConversationSummary
from app.answers.repository import ChatRepository
from app.answers.service import AnswerService, ChatConflict
from app.models import DocumentResponse, SearchRequest, SearchResponse
from app.processing.embeddings import EmbeddingService
from app.processing.errors import ProcessingError
from app.processing.worker import ProcessingWorker
from app.repository import SupabaseRepository
from app.security import VerifiedUser, require_user
from app.supabase_client import service_client
from app.operations import ControlsUnavailable, LibraryQuotaExceeded, LimitExceeded, OperationalControls
from app.http_middleware import OperationalMiddleware
from app.observability import configure_logging, metrics
from app.readiness import Readiness


def create_app(repository=None, embeddings=None, config: Settings | None = None, *, worker_enabled: bool | None = None, chat_repository=None, language_model=None, controls=None, readiness=None) -> FastAPI:
    """Construct the API with replaceable services for offline ownership tests."""
    config = config or settings
    repository = repository or SupabaseRepository(service_client, config)
    embeddings = embeddings or EmbeddingService(config)
    chats = chat_repository or ChatRepository(service_client, config.max_concurrent_answers_per_user)
    controls = controls or OperationalControls(service_client, config)
    readiness = readiness or Readiness(controls, embeddings, config)
    language_model = language_model or LanguageModel(config)
    answers = AnswerService(repository, chats, embeddings, language_model, config)
    enabled = config.processing_enabled if worker_enabled is None else worker_enabled
    worker = ProcessingWorker(repository, embeddings, config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging()
        if config.warm_models:
            await run_in_threadpool(embeddings.warmup)
        if enabled:
            worker.start()
        yield
        worker.stop()

    application = FastAPI(title="Book RAG Assistant API", version="0.4.0",
        docs_url=None if config.environment == 'production' else '/api/docs',
        openapi_url=None if config.environment == 'production' else '/openapi.json', redoc_url=None, lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)
    application.add_middleware(OperationalMiddleware, config=config)
    application.add_middleware(CORSMiddleware,
        allow_origins=[config.frontend_origin], allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"], expose_headers=['Retry-After','X-Request-ID'])

    async def limited_user(request: Request, user: VerifiedUser = Depends(require_user)):
        """Verify identity before charging shared budgets; no client owner ID is used."""
        path = getattr(request.scope.get('route'), 'path', '')
        action = 'read' if request.method == 'GET' else 'delete' if request.method == 'DELETE' else (
            'ask' if path.endswith('/ask') else 'search' if path.endswith('/search') else 'retry' if path.endswith('/retry') else 'upload')
        operation = None
        if action == 'ask':
            try:
                payload = await request.json()
                operation = UUID(str(payload.get('request_id'))) if isinstance(payload, dict) and payload.get('request_id') else None
            except (ValueError, TypeError):
                pass
        try:
            await run_in_threadpool(controls.consume, user.id, action, operation)
        except LimitExceeded as exc:
            raise HTTPException(429, str(exc), headers={'Retry-After': str(exc.retry_after)}) from exc
        except ControlsUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return user

    def owned_document(document_id: UUID, user: VerifiedUser) -> dict:
        """Use the verified token's owner before accessing a file, retry, or search."""
        try:
            row = repository.get_document(str(document_id), user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load this book. Please try again.") from exc
        if not row:
            raise HTTPException(status_code=404, detail="Book not found.")
        return row

    def owned_conversation(conversation_id: UUID, user: VerifiedUser) -> dict:
        """A conversation is private to its owner and permanently bound to one book."""
        try:
            row = chats.get_conversation(user.id, str(conversation_id))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load this conversation.") from exc
        if not row or not row.get("document_id"):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        owned_document(UUID(str(row["document_id"])), user)
        return row

    def answer_error(exc: Exception) -> HTTPException:
        """Translate expected state conflicts without leaking SQL/provider internals."""
        if isinstance(exc, ChatConflict):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, ModelUnavailable):
            return HTTPException(status_code=503, detail=str(exc))
        details = str(exc)
        if any(code in details for code in ("book_changed", "book_not_ready", "request_expired")):
            return HTTPException(status_code=409, detail="This book or conversation changed while answering. Refresh its status and try again.")
        if "request_conflict" in details:
            return HTTPException(status_code=409, detail="This request was already used for another question. Start a new question.")
        if "conversation_not_found" in details or "book_not_found" in details:
            return HTTPException(status_code=404, detail="Book or conversation not found.")
        return HTTPException(status_code=503, detail="Could not prepare or save this answer. Please try again.")

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "4", "processing": worker.state if enabled else "external", "answers": config.llm_provider}

    @application.get('/api/live')
    def live():
        return {'status': 'ok'}

    @application.get('/api/ready')
    def ready():
        checks = readiness.check()
        return JSONResponse({'status': 'ready' if all(checks.values()) else 'unavailable', 'checks': checks},
            status_code=200 if all(checks.values()) else 503)

    @application.get('/api/metrics')
    def operational_metrics(authorization: str | None = Header(default=None)):
        if not config.monitoring_token:
            raise HTTPException(404, 'Not found.')
        expected = 'Bearer ' + config.monitoring_token.get_secret_value()
        if not authorization or not compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, 'Monitoring authentication required.')
        try:
            return {**metrics.snapshot(), 'queue': controls.health()}
        except Exception as exc:
            raise HTTPException(503, 'Operational data is temporarily unavailable.') from exc

    @application.get('/api/usage')
    def usage(user: VerifiedUser = Depends(limited_user)):
        try:
            return controls.usage(user.id)
        except Exception as exc:
            raise HTTPException(503, 'Could not load your usage. Please try again.') from exc

    @application.get("/api/documents", response_model=list[DocumentResponse])
    def list_documents(user: VerifiedUser = Depends(limited_user)):
        """Processing status: return current stages, failures, and indexed counts."""
        try:
            return repository.list_documents(user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load your book library.") from exc

    @application.get("/api/documents/{document_id}", response_model=DocumentResponse)
    def get_document(document_id: UUID, user: VerifiedUser = Depends(limited_user)):
        return owned_document(document_id, user)

    @application.post("/api/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
    def upload_document(file: UploadFile = File(...), user: VerifiedUser = Depends(limited_user)):
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
        except LibraryQuotaExceeded as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="The PDF could not be saved. Please try again.") from exc
        if enabled:
            worker.wake()
        return row

    @application.post("/api/documents/{document_id}/retry", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
    def retry_document(document_id: UUID, user: VerifiedUser = Depends(limited_user)):
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
    def search_document(document_id: UUID, request: SearchRequest, user: VerifiedUser = Depends(limited_user)):
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
    def delete_document(document_id: UUID, user: VerifiedUser = Depends(limited_user)):
        """Remove the private file and owner-scoped row; indexed chunks cascade away."""
        row = owned_document(document_id, user)
        try:
            repository.delete_document(row, user.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="The book could not be deleted.")
        if enabled:
            worker.wake()
        return Response(status_code=204)

    # Grounded Q&A: only the book's verified owner can ask, resume, or read a chat.
    @application.post("/api/documents/{document_id}/ask", response_model=AnswerResponse)
    def ask_document(document_id: UUID, request: AskRequest, user: VerifiedUser = Depends(limited_user)):
        book = owned_document(document_id, user)
        if book["status"] != "ready":
            raise HTTPException(status_code=409, detail="This book is not ready for questions. Wait for processing or retry a failed book.")
        if request.conversation_id:
            conversation = owned_conversation(request.conversation_id, user)
            if str(conversation["document_id"]) != str(document_id):
                raise HTTPException(status_code=404, detail="Conversation not found for this book.")
        try:
            return answers.ask(user.id, book, request)
        except Exception as exc:
            raise answer_error(exc) from exc

    @application.get("/api/documents/{document_id}/conversations", response_model=list[ConversationSummary])
    def list_conversations(document_id: UUID, user: VerifiedUser = Depends(limited_user)):
        owned_document(document_id, user)
        try:
            return chats.list_conversations(user.id, str(document_id))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load your conversations.") from exc

    @application.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def read_conversation(conversation_id: UUID, before_sequence: int | None = Query(default=None, ge=1), user: VerifiedUser = Depends(limited_user)):
        """Return ordered history with immutable citations and optional older pages."""
        conversation = owned_conversation(conversation_id, user)
        try:
            messages, more = chats.message_page(str(conversation_id), before=before_sequence)
            return {"conversation": conversation, "messages": messages, "earlier_messages_available": more,
                "oldest_sequence": messages[0]["sequence_number"] if messages else None}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not load this conversation's messages.") from exc

    @application.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_conversation(conversation_id: UUID, user: VerifiedUser = Depends(limited_user)):
        owned_conversation(conversation_id, user)
        try:
            chats.delete_conversation(user.id, str(conversation_id))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not delete this conversation.") from exc
        return Response(status_code=204)

    return application


app = create_app()

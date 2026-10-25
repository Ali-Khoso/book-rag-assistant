from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.security import VerifiedUser, require_user
from app.supabase_client import service_client


app = FastAPI(title="Book RAG Assistant API", version="0.1.0", docs_url="/api/docs", redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    page_count: int | None = None
    created_at: str


def public_document(row: dict) -> DocumentResponse:
    return DocumentResponse(
        id=row["id"], filename=row["filename"], status=row["status"],
        page_count=row.get("page_count"), created_at=row["created_at"],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "1"}


@app.get("/api/documents", response_model=list[DocumentResponse])
def list_documents(user: VerifiedUser = Depends(require_user)):
    try:
        result = (
            service_client.table("documents")
            .select("id,filename,status,page_count,created_at")
            .eq("user_id", user.id)
            .order("created_at", desc=True)
            .execute()
        )
        return [public_document(row) for row in result.data or []]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not load your book library.") from exc


@app.post("/api/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), user: VerifiedUser = Depends(require_user)):
    original_name = (file.filename or "").replace("\\", "/")
    filename = PurePosixPath(original_name).name.strip()
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Choose a PDF file.")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="The uploaded file must have PDF content type.")

    try:
        content = file.file.read(settings.max_pdf_size_bytes + 1)
    finally:
        file.file.close()

    if len(content) > settings.max_pdf_size_bytes:
        raise HTTPException(status_code=413, detail="PDFs must be 6 MiB or smaller in Phase 1.")
    if b"%PDF-" not in content[:1024]:
        raise HTTPException(status_code=415, detail="The file does not contain a valid PDF signature.")

    document_id = uuid4()
    storage_path = f"{user.id}/{document_id}.pdf"
    safe_filename = filename[:180]
    try:
        # This ID is from a server-verified Supabase Auth response, never from the request body.
        service_client.table("users").upsert({"id": user.id, "auth_subject": user.id}, on_conflict="id").execute()
        service_client.storage.from_(settings.books_bucket).upload(
            storage_path, content, {"content-type": "application/pdf", "upsert": "false"}
        )
        inserted = service_client.table("documents").insert({
            "id": str(document_id), "user_id": user.id, "filename": safe_filename,
            "storage_key": storage_path, "status": "queued",
        }).execute()
        if not inserted.data:
            raise RuntimeError("Document row was not returned")
        return public_document(inserted.data[0])
    except Exception as exc:
        # Best-effort cleanup prevents an orphaned private file if saving its row fails.
        try:
            service_client.storage.from_(settings.books_bucket).remove([storage_path])
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="The PDF could not be saved. Please try again.") from exc


@app.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: UUID, user: VerifiedUser = Depends(require_user)):
    try:
        found = (
            service_client.table("documents")
            .select("id,storage_key")
            .eq("id", str(document_id))
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )
        row = found.data
        if not row:
            raise HTTPException(status_code=404, detail="Book not found.")
        service_client.storage.from_(settings.books_bucket).remove([row["storage_key"]])
        service_client.table("documents").delete().eq("id", str(document_id)).eq("user_id", user.id).execute()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="The book could not be deleted.") from exc

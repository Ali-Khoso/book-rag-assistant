"""Public API models: book processing status and retrieved source passages."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    status: Literal["queued", "processing", "ready", "failed"]
    page_count: int | None = None
    created_at: str
    processing_error: str | None = None
    processing_stage: str | None = None
    chunk_count: int = 0
    processed_at: str | None = None


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def readable_question(cls, value: str) -> str:
        """Reject whitespace-only questions before calling the embedding model."""
        value = value.strip()
        if not value:
            raise ValueError("Enter a question to search this book")
        return value


class PassageResponse(BaseModel):
    id: UUID
    document_id: UUID
    content: str
    page_start: int
    page_end: int
    chunk_index: int
    similarity: float


class SearchResponse(BaseModel):
    document_id: UUID
    question: str
    passages: list[PassageResponse]

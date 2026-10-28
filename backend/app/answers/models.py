"""Typed answer contracts; language models cannot choose public page citations."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models import SearchRequest


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=600)


class ModelStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=900)
    citations: list[EvidenceReference] = Field(min_length=1, max_length=3)


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    statements: list[ModelStatement] = Field(max_length=4)


class AskRequest(SearchRequest):
    top_k: int = Field(default=6, ge=1, le=10)
    request_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID | None = None


class AnswerStatement(BaseModel):
    text: str
    citation_ranks: list[int]


class CitationSnapshot(BaseModel):
    rank: int
    source_kind: Literal["passage", "metadata"]
    chunk_id: UUID | None
    document_id: UUID
    filename: str
    page_start: int | None
    page_end: int | None
    excerpt: str
    quote: str


class AnswerPayload(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    method: Literal["metadata", "model"]
    content: str
    scope_note: str | None = None
    statements: list[AnswerStatement]
    citations: list[CitationSnapshot] = Field(default_factory=list)


class AnswerResponse(BaseModel):
    conversation_id: UUID
    request_id: UUID
    user_message_id: UUID
    message_id: UUID
    document_id: UUID
    question: str
    created_at: str
    answer: AnswerPayload


class ConversationSummary(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    created_at: str
    updated_at: str


class ChatMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    sequence_number: int
    created_at: str
    answer_payload: AnswerPayload | None = None


class ConversationResponse(BaseModel):
    conversation: ConversationSummary
    messages: list[ChatMessage]
    earlier_messages_available: bool = False
    oldest_sequence: int | None = None

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    frontend_origin: str = "http://localhost:3000"
    books_bucket: str = "books-private"
    max_pdf_size_bytes: int = 50 * 1024 * 1024

    # PDF text extraction and text chunking: bound work before generating vectors.
    max_pdf_pages: int = Field(default=2000, ge=1, le=10000)
    max_extracted_chars: int = Field(default=5_000_000, ge=1000)
    chunk_size_chars: int = Field(default=1400, ge=256, le=4000)
    chunk_overlap_chars: int = Field(default=200, ge=0)
    max_document_chunks: int = Field(default=5000, ge=1)

    # Embeddings: local inference needs no API key; hosted credentials stay here.
    embedding_provider: Literal["local", "api"] = "local"
    embedding_model: str = "minishlab/potion-base-8M"
    embedding_revision: str = "bf8b056651a2c21b8d2565580b8569da283cab23"
    embedding_dimensions: Literal[256] = 256
    model_cache_dir: str = ".cache/models"
    embedding_api_url: str = ""
    embedding_api_key: SecretStr | None = None
    embedding_batch_size: int = Field(default=64, ge=1, le=128)

    # Processing status and retry: the queue lives in Postgres, not browser memory.
    processing_enabled: bool = True
    processing_poll_seconds: float = Field(default=3, ge=1, le=60)

    # Phase 3: language-model credentials remain on the API server only.
    llm_provider: Literal["ollama", "openai"] = "ollama"
    llm_model: str = "qwen2.5:3b"
    ollama_url: str = "http://127.0.0.1:11434"
    openai_api_key: SecretStr | None = None
    llm_timeout_seconds: int = Field(default=180, ge=10, le=240)
    answer_retrieval_k: int = Field(default=6, ge=1, le=10)
    answer_context_chars: int = Field(default=9000, ge=1500, le=16000)
    answer_min_similarity: float = Field(default=0.25, ge=0, le=1)
    conversation_history_turns: int = Field(default=4, ge=0, le=10)

    @model_validator(mode="after")
    def validate_processing_settings(self):
        """Reject settings that would lose overlap progress or expose API credentials."""
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS")
        if self.embedding_provider == "api":
            if not self.embedding_api_url.startswith("https://") or not self.embedding_api_key or not self.embedding_api_key.get_secret_value().strip():
                raise ValueError("Hosted embeddings require an HTTPS URL and EMBEDDING_API_KEY")
        if self.llm_provider == "openai":
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OpenAI answers require OPENAI_API_KEY in backend/.env")
            if self.llm_model.startswith("qwen"):
                raise ValueError("Set LLM_MODEL to a structured-output OpenAI model for the OpenAI provider")
        if self.llm_provider == "ollama" and not self.ollama_url.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
            raise ValueError("Ollama must use loopback HTTP or an HTTPS endpoint")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)


settings = Settings()

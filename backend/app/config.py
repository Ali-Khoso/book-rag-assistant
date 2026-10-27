from typing import Literal
from urllib.parse import urlsplit
import os

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    frontend_origin: str = "http://localhost:3000"
    books_bucket: str = "books-private"
    max_pdf_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)

    # Phase 4: shared quotas and safe production defaults.
    environment: Literal['development', 'test', 'production'] = 'development'
    limits_enabled: bool = True
    max_books_per_user: int = Field(default=20, ge=1, le=1000)
    max_storage_bytes_per_user: int = Field(default=500 * 1024 * 1024, ge=1024)
    read_requests_per_minute: int = Field(default=120, ge=1)
    upload_requests_per_minute: int = Field(default=5, ge=1)
    search_requests_per_minute: int = Field(default=20, ge=1)
    ask_requests_per_minute: int = Field(default=5, ge=1)
    questions_per_day: int = Field(default=100, ge=1)
    uploads_per_day: int = Field(default=20, ge=1)
    max_concurrent_answers_per_user: int = Field(default=1, ge=1, le=10)
    processing_max_attempts: int = Field(default=3, ge=1, le=10)
    deletion_max_attempts: int = Field(default=8, ge=1, le=20)
    worker_heartbeat_seconds: int = Field(default=10, ge=2, le=15)
    monitoring_token: SecretStr | None = None
    allowed_hosts: list[str] = ['localhost', '127.0.0.1', 'testserver']
    warm_models: bool = False
    max_json_body_bytes: int = Field(default=32768, ge=4096, le=262144)

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
    ollama_allowed_http_hosts: list[str] = ['127.0.0.1', 'localhost', 'ollama']
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
        self.frontend_origin = self.frontend_origin.rstrip('/')
        if self.embedding_provider == "api":
            if not self.embedding_api_url.startswith("https://") or not self.embedding_api_key or not self.embedding_api_key.get_secret_value().strip():
                raise ValueError("Hosted embeddings require an HTTPS URL and EMBEDDING_API_KEY")
        if self.llm_provider == "openai":
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OpenAI answers require OPENAI_API_KEY in backend/.env")
            if self.llm_model.startswith("qwen"):
                raise ValueError("Set LLM_MODEL to a structured-output OpenAI model for the OpenAI provider")
        model_url = urlsplit(self.ollama_url)
        if self.llm_provider == 'ollama' and not (model_url.scheme == 'https' or (
            model_url.scheme == 'http' and model_url.hostname in self.ollama_allowed_http_hosts)):
            raise ValueError("Ollama must use loopback HTTP or an HTTPS endpoint")
        if self.environment == 'production':
            if any('REPLACE_ME' in value or 'YOUR_PRODUCTION_PROJECT' in value for value in (
                self.supabase_url, self.supabase_publishable_key, self.supabase_secret_key)):
                raise ValueError('Replace production Supabase placeholders before starting')
            origin = urlsplit(self.frontend_origin)
            if origin.scheme != 'https' or origin.hostname in ('localhost', '127.0.0.1') or origin.path not in ('', '/') or origin.query or origin.fragment:
                raise ValueError('Production requires an HTTPS FRONTEND_ORIGIN without a path')
            if not self.supabase_url.startswith('https://') or not self.limits_enabled:
                raise ValueError('Production requires HTTPS Supabase and enabled usage limits')
            if not self.allowed_hosts or any('*' in host or host == 'testserver' for host in self.allowed_hosts):
                raise ValueError('Set ALLOWED_HOSTS explicitly for production')
            if self.monitoring_token:
                token = self.monitoring_token.get_secret_value()
                if len(token) < 32 or token.startswith(('REPLACE', 'your_')):
                    raise ValueError('MONITORING_TOKEN must be a private random token of at least 32 characters')
        return self

    model_config = SettingsConfigDict(env_file=os.environ.get('BOOKWISE_ENV_FILE', '.env'), extra="ignore", hide_input_in_errors=True)


settings = Settings()

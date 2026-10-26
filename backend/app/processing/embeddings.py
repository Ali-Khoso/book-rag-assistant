"""Embeddings: use one pinned semantic model for both passages and questions."""

import hashlib
import math
from pathlib import Path
from threading import RLock

import httpx

from app.config import Settings
from app.processing.errors import ProcessingError


class EmbeddingService:
    """Cache local model weights; keep optional hosted API credentials server-only."""

    def __init__(self, config: Settings):
        self.config = config
        self._model = None
        self._lock = RLock()

    @property
    def model_id(self) -> str:
        """Include revision/provider so vectors from different spaces never mix."""
        config = self.config
        endpoint = hashlib.sha256(config.embedding_api_url.encode()).hexdigest()[:12] if config.embedding_provider == "api" else "cpu"
        return f"{config.embedding_provider}:{config.embedding_model}:{config.embedding_revision}:{endpoint}:256"

    def warmup(self) -> None:
        """Download the pinned local weights once, then load from the project cache."""
        if self.config.embedding_provider != "local":
            return
        with self._lock:
            if self._model is None:
                from huggingface_hub import snapshot_download
                from model2vec import StaticModel

                folder = snapshot_download(
                    repo_id=self.config.embedding_model,
                    revision=self.config.embedding_revision,
                    cache_dir=str(Path(self.config.model_cache_dir).resolve()),
                    allow_patterns=["config.json", "tokenizer.json", "model.safetensors"],
                    max_workers=2,
                )
                self._model = StaticModel.from_pretrained(folder, force_download=False)
                if self._model.dim != self.config.embedding_dimensions:
                    self._model = None
                    raise ProcessingError("The embedding model dimensions do not match this book index.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Validate and normalize every vector before it reaches pgvector."""
        if not texts:
            return []
        try:
            if self.config.embedding_provider == "local":
                with self._lock:
                    self.warmup()
                    vectors = self._model.encode(texts, max_length=None, show_progress_bar=False, use_multiprocessing=False).tolist()
            else:
                vectors = self._embed_api(texts)
            if len(vectors) != len(texts):
                raise ValueError("Embedding count mismatch")
            result = []
            for vector in vectors:
                if len(vector) != 256 or not all(math.isfinite(value) for value in vector):
                    raise ValueError("Invalid vector")
                norm = math.sqrt(sum(value * value for value in vector))
                if norm < 1e-12:
                    raise ProcessingError("No searchable words were found. Try a more descriptive question or a text-based PDF.")
                result.append([float(value / norm) for value in vector])
            return result
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("The embedding model is unavailable. Check the backend connection or model settings, then retry.") from exc

    def _embed_api(self, texts: list[str]) -> list[list[float]]:
        """Support a configured HTTPS embedding endpoint without exposing its key."""
        with httpx.Client(timeout=60) as client:
            response = client.post(self.config.embedding_api_url,
                headers={"Authorization": f"Bearer {self.config.embedding_api_key.get_secret_value()}"},
                json={"model": self.config.embedding_model, "input": texts, "dimensions": 256})
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            if [item["index"] for item in data] != list(range(len(texts))):
                raise ValueError("Invalid embedding indices")
            return [item["embedding"] for item in data]

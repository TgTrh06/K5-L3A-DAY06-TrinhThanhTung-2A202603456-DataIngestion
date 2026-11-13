"""Local Sentence Transformers adapter for real dense embeddings."""

from __future__ import annotations

import os
from typing import Protocol


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class SentenceTransformerEmbedder:
    """Load one local model and use it consistently for documents and queries."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        resolved_model = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; install starter/requirements.txt"
            ) from exc

        self.model_name = resolved_model
        self.batch_size = batch_size
        try:
            self._model = SentenceTransformer(resolved_model, device=device)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load embedding model {resolved_model!r}. "
                "Check model access and network availability."
            ) from exc

        dimensions = self._model.get_embedding_dimension()
        if not dimensions or dimensions <= 0:
            raise RuntimeError(f"Model {resolved_model!r} did not report a valid vector size")
        self.dimensions = int(dimensions)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding inputs must be non-empty strings")

        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        result = vectors.tolist()
        if len(result) != len(texts):
            raise RuntimeError("embedding model returned a different number of vectors")
        if any(len(vector) != self.dimensions for vector in result):
            raise RuntimeError("embedding model returned vectors with inconsistent dimensions")
        return [[float(value) for value in vector] for vector in result]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, question: str) -> list[float]:
        vectors = self._encode([question])
        return vectors[0]

"""Embedding generation using sentence-transformers."""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class Embedder:
    """Generates embeddings using sentence-transformers with GPU support."""

    def __init__(self, model_name: str = "mixedbread-ai/mxbai-embed-large-v1",
                 device: str = "cuda", batch_size: int = 64):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._dimension: Optional[int] = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
            logger.info("Loading embedding model: %s (device=%s)", self.model_name, self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info("Embedding dimension: %d", self._dimension)

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        self._load_model()
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats).
        """
        self._load_model()

        if not texts:
            return []

        embeddings = self._model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        if isinstance(embeddings, np.ndarray):
            return embeddings.tolist()
        return [e.tolist() for e in embeddings]

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string."""
        result = self.embed([query])
        return result[0]

"""Single owner of the sentence-transformer model.

Every consumer (semantic cache, feedback few-shots, trajectory memory, RAG
retrieval) shares one lazily-loaded encoder so the model is downloaded and held
in RAM exactly once. When the optional ``sentence-transformers`` dependency is
unavailable the service degrades to a deterministic hashing encoder, which keeps
similarity search usable offline instead of disabling the feature outright.
"""

from __future__ import annotations

import hashlib
import threading

import numpy as np

from src.config import settings
from src.utils.logging import logger


HASH_DIM = 384  # matches all-MiniLM-L6-v2 so stored vectors stay interchangeable in size


def cosine_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Cosine similarity that is total: unusable inputs score 0.0 rather than raising."""
    if a is None or b is None:
        return 0.0
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 0.0
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class _HashingEncoder:
    """Offline fallback: bag-of-tokens hashed into a fixed-width vector.

    Not semantically meaningful across paraphrases, but it is stable, cheap and
    makes exact/near-duplicate lookups work without any model download.
    """

    dimension = HASH_DIM

    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        for token in str(text).lower().split():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec


class EmbeddingService:
    def __init__(self, model_name: str | None = None, *, use_fallback: bool = False):
        """
        Args:
            model_name: sentence-transformers model id.
            use_fallback: skip the transformer entirely and always use the
                hashing encoder. Useful for air-gapped deployments and for tests,
                which must not attempt a model download.
        """
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self._model = None
        self._fallback: _HashingEncoder | None = None
        self._lock = threading.Lock()
        self._load_failed = use_fallback

    @property
    def is_semantic(self) -> bool:
        """True when the real transformer model is loaded (not the hashing fallback)."""
        return self._model is not None

    def _get_model(self):
        if self._model is not None or self._load_failed:
            return self._model
        with self._lock:
            if self._model is not None or self._load_failed:
                return self._model
            try:
                logger.info("Loading SentenceTransformer model", model=self.model_name)
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                logger.info("SentenceTransformer ready", model=self.model_name)
            except Exception as exc:
                # Missing package, no network on first download, or low memory.
                self._load_failed = True
                logger.warning(
                    "Embedding model unavailable, falling back to hashing encoder",
                    model=self.model_name,
                    error=str(exc),
                )
        return self._model

    def _get_fallback(self) -> _HashingEncoder:
        if self._fallback is None:
            self._fallback = _HashingEncoder()
        return self._fallback

    def encode(self, text: str) -> np.ndarray:
        """Encodes a single string. Never raises."""
        model = self._get_model()
        if model is not None:
            try:
                return np.asarray(model.encode(text), dtype=np.float32)
            except Exception as exc:
                logger.warning("Embedding encode failed, using fallback", error=str(exc))
        return self._get_fallback().encode(text)

    def encode_many(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        model = self._get_model()
        if model is not None:
            try:
                vectors = model.encode(texts)
                return [np.asarray(v, dtype=np.float32) for v in vectors]
            except Exception as exc:
                logger.warning("Batch embedding failed, using fallback", error=str(exc))
        fallback = self._get_fallback()
        return [fallback.encode(t) for t in texts]

    def similarity(self, a: np.ndarray | None, b: np.ndarray | None) -> float:
        return cosine_similarity(a, b)

    def rank(self, query: str, candidates: list[tuple[str, np.ndarray | None]]) -> list[tuple[float, int]]:
        """Scores ``candidates`` against ``query``; returns (score, index) sorted desc.

        Candidates whose stored embedding is missing are encoded on the fly so a
        partially-populated table still ranks correctly.
        """
        if not candidates:
            return []
        query_vec = self.encode(query)
        scored: list[tuple[float, int]] = []
        for idx, (text, vector) in enumerate(candidates):
            vec = vector if vector is not None and len(vector) else self.encode(text)
            scored.append((self.similarity(query_vec, vec), idx))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored


embedding_service = EmbeddingService(use_fallback=settings.EMBEDDINGS_FORCE_FALLBACK)

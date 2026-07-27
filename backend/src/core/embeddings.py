"""Single owner of text embeddings, in whatever form this install can provide.

Every consumer -- semantic cache, feedback few-shots, trajectory memory, RAG
retrieval, document search -- goes through one service, so a vector is produced
the same way wherever it is compared.

Why this no longer defaults to ``sentence-transformers``
-------------------------------------------------------
That package depends on torch, and on Linux/x86_64 torch declares eleven
``nvidia-*-cu12`` wheels as hard requirements, installed whether or not the
machine has a GPU. Measured against the pinned versions that is ~2.8 GB of
compressed wheels -- roughly six gigabytes installed -- to run a 90 MB MiniLM
model. It was the single largest thing in the backend image, larger than the
entire analysis sandbox.

The model server this app already talks to can embed, so it is asked instead:

1. **the selected provider** -- Ollama's ``POST /api/embed``, or the OpenAI-style
   ``POST /v1/embeddings`` that LM Studio and every gateway expose. Costs
   nothing on disk and follows whichever backend the user chose.
2. **local sentence-transformers**, if the user installed it deliberately.
3. **a hashing encoder**, which is not semantic but is stable, instant and
   works with no model and no network -- so nothing ever hard-fails.

Nothing here raises. A retrieval feature degrading is always better than a
question failing.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import numpy as np

from src.config import settings
from src.utils.logging import logger


HASH_DIM = 384  # matches all-MiniLM-L6-v2 so stored vectors stay interchangeable in size

#: How long to wait before retrying a remote encoder that could not be reached.
#: Without this every single encode on an offline machine pays a connect
#: timeout, and encodes happen several times per question.
REMOTE_RETRY_SECONDS = 120.0


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


class _RemoteEncoder:
    """Embeddings from the model server the app is already configured against.

    Ollama and the OpenAI-compatible servers differ in both the path and the
    response shape, which is the whole of the difference between them here.
    """

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self._client: Any = None
        self._lock = threading.Lock()

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def _http(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import httpx

                    self._client = httpx.Client(timeout=settings.EMBEDDING_TIMEOUT)
        return self._client

    def _endpoint_and_payload(self, texts: list[str]) -> tuple[str, dict[str, Any]]:
        if self.provider == "ollama":
            root = settings.provider_root_url(self.provider).rstrip("/")
            return f"{root}/api/embed", {"model": self.model, "input": texts}
        base = settings.provider_openai_base_url(self.provider).rstrip("/")
        return f"{base}/embeddings", {"model": self.model, "input": texts}

    @staticmethod
    def _vectors_from(payload: dict[str, Any]) -> list[list[float]]:
        # Ollama: {"embeddings": [[...]]}. OpenAI-compatible: {"data": [{"embedding": [...]}]},
        # which is *not* guaranteed to come back in request order, so it is sorted by index.
        if isinstance(payload.get("embeddings"), list):
            return payload["embeddings"]
        data = payload.get("data")
        if isinstance(data, list):
            ordered = sorted(data, key=lambda row: row.get("index", 0) if isinstance(row, dict) else 0)
            return [row.get("embedding", []) for row in ordered if isinstance(row, dict)]
        return []

    def encode_many(self, texts: list[str]) -> list[np.ndarray] | None:
        """Vectors for ``texts``, or ``None`` if this encoder could not serve them."""
        url, payload = self._endpoint_and_payload(texts)
        headers = {}
        key = settings.provider_api_key(self.provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            response = self._http().post(url, json=payload, headers=headers)
            response.raise_for_status()
            vectors = self._vectors_from(response.json())
        except Exception as exc:
            logger.warning("Remote embedding failed", provider=self.provider, model=self.model, error=str(exc))
            return None

        if len(vectors) != len(texts) or not all(vectors):
            logger.warning(
                "Remote embedding returned an unusable payload",
                provider=self.provider,
                expected=len(texts),
                received=len(vectors),
            )
            return None
        return [np.asarray(vector, dtype=np.float32) for vector in vectors]


class EmbeddingService:
    def __init__(self, model_name: str | None = None, *, use_fallback: bool = False):
        """
        Args:
            model_name: sentence-transformers model id, used only on the local path.
            use_fallback: skip every real encoder and always use the hashing one.
                Needed for air-gapped deployments and for tests, which must not
                download a model or contact a model server.
        """
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self._model = None
        self._remote: _RemoteEncoder | None = None
        self._remote_checked = False
        self._remote_failed_at = 0.0
        self._fallback: _HashingEncoder | None = None
        self._lock = threading.Lock()
        self._load_failed = use_fallback
        self._forced_fallback = use_fallback

    # ------------------------------------------------------------------ #
    @property
    def is_semantic(self) -> bool:
        """True when a real model produces the vectors, remote or local."""
        return self._remote is not None or self._model is not None

    @property
    def backend(self) -> str:
        """What is actually producing vectors, for the diagnostics readout."""
        if self._remote is not None:
            return f"provider:{self._remote.label}"
        if self._model is not None:
            return f"local:{self.model_name}"
        return "lexical"

    # ------------------------------------------------------------------ #
    def _get_remote(self) -> _RemoteEncoder | None:
        """Resolves an embedding model on the configured provider, once.

        A provider that has no embedding model installed is the common case, so
        the negative result is remembered and only retried occasionally --
        otherwise every encode on a machine with no such model pays a discovery
        round-trip, several times per question.
        """
        if self._forced_fallback or not settings.EMBEDDINGS_REMOTE_ENABLED:
            return None
        if self._remote is not None:
            return self._remote
        if self._remote_checked and (time.monotonic() - self._remote_failed_at) < REMOTE_RETRY_SECONDS:
            return None

        with self._lock:
            if self._remote is not None:
                return self._remote
            self._remote_checked = True
            self._remote_failed_at = time.monotonic()

            provider = settings.resolve_provider(settings.EMBEDDING_PROVIDER or None)
            model = settings.EMBEDDING_REMOTE_MODEL.strip() or self._discover_model(provider)
            if not model:
                return None

            candidate = _RemoteEncoder(provider, model)
            # Prove it works before adopting it: a name that classifies as an
            # embedding model is not the same as one the server will embed with.
            if candidate.encode_many(["wizard embedding probe"]) is None:
                return None
            self._remote = candidate
            logger.info("Embeddings served by provider", provider=provider, model=model)
            return self._remote

    @staticmethod
    def _discover_model(provider: str) -> str:
        """An installed embedding model on ``provider``, or ``""``.

        Uses the registry's own classification -- LM Studio reports the type
        outright, and for Ollama it is inferred from the tag -- rather than a
        second, differently-wrong list of model names kept here.
        """
        try:
            from src.core.llm import model_registry

            models = model_registry.list_models(provider=provider)
        except Exception as exc:
            logger.warning("Embedding model discovery failed", provider=provider, error=str(exc))
            return ""
        for model in models:
            if "embedding" in (model.capabilities or []):
                return model.name
        return ""

    def _get_model(self):
        """The optional local sentence-transformers model, if it is installed."""
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
                # Not installed (the normal case now), no network for the first
                # download, or too little memory.
                self._load_failed = True
                logger.info(
                    "No local embedding model; using the provider or the hashing encoder",
                    model=self.model_name,
                    detail=str(exc),
                )
        return self._model

    def _get_fallback(self) -> _HashingEncoder:
        if self._fallback is None:
            self._fallback = _HashingEncoder()
        return self._fallback

    # ------------------------------------------------------------------ #
    def encode(self, text: str) -> np.ndarray:
        """Encodes a single string. Never raises."""
        return self.encode_many([text])[0]

    def encode_many(self, texts: list[str]) -> list[np.ndarray]:
        """Encodes a batch. Never raises, and always returns one vector per input."""
        if not texts:
            return []

        remote = self._get_remote()
        if remote is not None:
            vectors = remote.encode_many(texts)
            if vectors is not None:
                return vectors
            # A working encoder that just failed is a transient problem, not a
            # reason to keep paying for it on every subsequent call.
            self._remote = None
            self._remote_failed_at = time.monotonic()

        model = self._get_model()
        if model is not None:
            try:
                return [np.asarray(vector, dtype=np.float32) for vector in model.encode(texts)]
            except Exception as exc:
                logger.warning("Local embedding failed, using fallback", error=str(exc))

        fallback = self._get_fallback()
        return [fallback.encode(text) for text in texts]

    def similarity(self, a: np.ndarray | None, b: np.ndarray | None) -> float:
        return cosine_similarity(a, b)

    def rank(self, query: str, candidates: list[tuple[str, np.ndarray | None]]) -> list[tuple[float, int]]:
        """Scores ``candidates`` against ``query``; returns (score, index) sorted desc.

        A stored vector is re-encoded when it is missing *or* when its width does
        not match the query's. Switching encoder -- MiniLM's 384 dimensions to a
        768-dimension provider model, or back to the hashing fallback -- would
        otherwise score every previously-stored row at exactly 0.0, silently
        emptying the semantic cache and the trajectory memory rather than
        rebuilding them.
        """
        if not candidates:
            return []
        query_vec = self.encode(query)
        width = query_vec.size

        stale = [
            index
            for index, (_, vector) in enumerate(candidates)
            if vector is None or len(vector) == 0 or np.asarray(vector).size != width
        ]
        refreshed: dict[int, np.ndarray] = {}
        if stale:
            encoded = self.encode_many([candidates[index][0] for index in stale])
            refreshed = dict(zip(stale, encoded, strict=False))

        scored = [
            (self.similarity(query_vec, refreshed.get(index, vector)), index)
            for index, (_, vector) in enumerate(candidates)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored


embedding_service = EmbeddingService(use_fallback=settings.EMBEDDINGS_FORCE_FALLBACK)

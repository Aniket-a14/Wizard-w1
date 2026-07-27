"""Embeddings without torch.

`sentence-transformers` depends on torch, which on linux/x86_64 hard-depends on
eleven `nvidia-*-cu12` wheels -- about 2.8 GB of compressed wheels, installed
whether or not there is a GPU, to run a 90 MB MiniLM model. It was the largest
single thing in the backend image.

Vectors now come from the model server the app already talks to, and these tests
pin the parts that differ per provider plus the one failure mode that would be
silent: switching encoder changes the vector width, and every stored vector
would otherwise score exactly 0.0 forever.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.core.embeddings import EmbeddingService, _RemoteEncoder, cosine_similarity


# --------------------------------------------------------------------------- #
# Provider response shapes
# --------------------------------------------------------------------------- #
def test_ollama_response_shape_is_understood() -> None:
    vectors = _RemoteEncoder._vectors_from({"model": "embeddinggemma", "embeddings": [[1.0, 2.0]]})
    assert vectors == [[1.0, 2.0]]


def test_openai_compatible_response_shape_is_understood() -> None:
    payload = {"data": [{"index": 0, "embedding": [1.0, 2.0]}, {"index": 1, "embedding": [3.0, 4.0]}]}
    assert _RemoteEncoder._vectors_from(payload) == [[1.0, 2.0], [3.0, 4.0]]


def test_openai_results_are_ordered_by_index_not_by_arrival() -> None:
    """The spec does not promise request order, and a swap here would attach
    every embedding to the wrong text -- which no assertion downstream catches,
    because a wrong vector is still a valid vector.
    """
    payload = {"data": [{"index": 1, "embedding": [3.0]}, {"index": 0, "embedding": [1.0]}]}
    assert _RemoteEncoder._vectors_from(payload) == [[1.0], [3.0]]


def test_an_unrecognised_payload_yields_nothing_rather_than_guessing() -> None:
    assert _RemoteEncoder._vectors_from({"error": "model not found"}) == []


@pytest.mark.parametrize(
    ("provider", "suffix"),
    [("ollama", "/api/embed"), ("lmstudio", "/v1/embeddings"), ("custom_gateway", "/embeddings")],
)
def test_each_provider_is_asked_at_its_own_endpoint(provider: str, suffix: str) -> None:
    """Ollama's embed API is native; everything else is OpenAI-compatible."""
    url, payload = _RemoteEncoder(provider, "m")._endpoint_and_payload(["a", "b"])
    assert url.endswith(suffix)
    assert payload["input"] == ["a", "b"]
    assert payload["model"] == "m"


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #
def test_forced_fallback_never_contacts_a_provider(monkeypatch) -> None:
    """CI and air-gapped installs must not dial out on an encode."""
    service = EmbeddingService(use_fallback=True)

    def explode(*_args, **_kwargs):  # pragma: no cover - reached only on regression
        raise AssertionError("a remote encoder must not be built in fallback mode")

    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", explode)
    vector = service.encode("revenue by region")

    assert vector.shape == (384,)
    assert service.is_semantic is False
    assert service.backend == "lexical"


def test_encoding_always_returns_one_vector_per_input() -> None:
    service = EmbeddingService(use_fallback=True)
    assert len(service.encode_many(["a", "b", "c"])) == 3
    assert service.encode_many([]) == []


def test_a_failing_remote_encoder_is_dropped_rather_than_retried_each_call() -> None:
    """An encode happens several times per question. Paying a connect timeout
    on every one of them would make an offline machine feel broken.
    """
    service = EmbeddingService(use_fallback=True)
    service._forced_fallback = False
    service._remote = _RemoteEncoder("ollama", "nomic-embed-text")
    service._load_failed = True

    calls: list[int] = []

    def fail(texts):
        calls.append(len(texts))
        return None

    service._remote.encode_many = fail  # type: ignore[method-assign]
    service.encode("first")
    service.encode("second")

    assert len(calls) == 1, "the dead encoder should not be consulted again"
    assert service._remote is None


# --------------------------------------------------------------------------- #
# Changing encoder must not silently empty the caches
# --------------------------------------------------------------------------- #
def test_similarity_of_differently_sized_vectors_is_zero_not_an_error() -> None:
    assert cosine_similarity(np.ones(384, dtype=np.float32), np.ones(768, dtype=np.float32)) == 0.0


def test_ranking_re_encodes_vectors_stored_at_a_different_width() -> None:
    """Switching from MiniLM's 384 dimensions to a 768-dimension provider model
    would otherwise score every previously-stored row at exactly 0.0 -- the
    semantic cache and the trajectory memory would look empty rather than stale,
    and would never rebuild.
    """
    service = EmbeddingService(use_fallback=True)
    stale = np.ones(768, dtype=np.float32)  # written by a different encoder

    ranked = service.rank("total revenue", [("total revenue", stale), ("unrelated text", None)])
    scores = {index: score for score, index in ranked}

    assert scores[0] > 0.9, "an exact match must survive an encoder change"
    assert ranked[0][1] == 0


def test_ranking_leaves_matching_width_vectors_alone() -> None:
    service = EmbeddingService(use_fallback=True)
    stored = service.encode("total revenue")
    ranked = service.rank("total revenue", [("ignored text", stored)])
    # Scored against the stored vector, not against the candidate's own text.
    assert ranked[0][0] > 0.9

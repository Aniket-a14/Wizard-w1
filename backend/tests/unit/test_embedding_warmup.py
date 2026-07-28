"""Resolving an encoder must never happen inside somebody's question.

The defect these pin cost a real run nine minutes with the model server idle the
whole time. Cold-starting an encoder is a different operation from using one:
the server has to read the model off disk first. Measured on a laptop that took
over 20s, which is longer than the steady-state request timeout -- so the very
first encode of every boot timed out, the provider was written off as broken,
and the install spent the rest of its life on lexical retrieval while paying to
download a 90 MB model it then failed to use.

Every subsequent encode against that same provider took 0.05s.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from src.config import settings
from src.core.embeddings import (
    REMOTE_RETRY_MAX_SECONDS,
    REMOTE_RETRY_SECONDS,
    EmbeddingService,
)


class _SlowFirstCall:
    """A provider that is slow exactly once -- the cold model load."""

    label = "stub:an-embedding-model"

    def __init__(self, cold_seconds: float = 60.0, dim: int = 768):
        self.cold_seconds = cold_seconds
        self.dim = dim
        self.calls: list[float | None] = []

    def encode_many(self, texts, timeout=None):
        self.calls.append(timeout)
        budget = timeout if timeout is not None else settings.EMBEDDING_TIMEOUT
        if len(self.calls) == 1 and budget < self.cold_seconds:
            return None  # timed out before the model finished loading
        return [np.ones(self.dim, dtype=np.float32) for _ in texts]


@pytest.fixture
def service(monkeypatch):
    """A service with discovery stubbed out, so nothing touches the network."""
    svc = EmbeddingService()
    monkeypatch.setattr(EmbeddingService, "_discover_model", staticmethod(lambda provider: "an-embedding-model"))
    return svc


def test_the_cold_probe_is_given_a_cold_timeout(service, monkeypatch):
    """A model load must not be judged against a steady-state request timeout."""
    encoder = _SlowFirstCall()
    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", lambda provider, model: encoder)

    service.warm(block=True, timeout=10)

    assert encoder.calls, "the provider was never probed"
    assert encoder.calls[0] == settings.EMBEDDING_COLD_TIMEOUT
    assert settings.EMBEDDING_COLD_TIMEOUT > settings.EMBEDDING_TIMEOUT
    assert service.is_semantic, "a provider that answers after a cold load must be adopted"


def test_a_slow_cold_load_no_longer_loses_the_provider(service, monkeypatch):
    """The regression itself: 20s was not enough, and the encoder was discarded.

    With the cold timeout the same provider is adopted, and retrieval stays
    semantic instead of silently degrading to word overlap.
    """
    encoder = _SlowFirstCall(cold_seconds=60.0)
    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", lambda provider, model: encoder)

    service.warm(block=True, timeout=10)
    vectors = service.encode_many(["how much revenue by region"])

    assert service.backend.startswith("provider:")
    assert vectors[0].size == 768


def test_a_question_never_waits_for_warm_up(service, monkeypatch):
    """While the encoder is resolving, encode answers immediately.

    Blocking would put a model load on the critical path of a question, which is
    the whole thing being fixed. Retrieval is worse for those few seconds; the
    question is not slower by a second.
    """

    class _Blocking:
        label = "stub:slow"

        def encode_many(self, texts, timeout=None):
            time.sleep(0.4)
            return [np.ones(768, dtype=np.float32) for _ in texts]

    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", lambda provider, model: _Blocking())

    service.warm()  # non-blocking, resolution now in flight
    began = time.monotonic()
    vectors = service.encode_many(["a question asked immediately"])
    elapsed = time.monotonic() - began

    assert elapsed < 0.2, "the question waited for the encoder to resolve"
    assert vectors[0].size > 0, "it still got a usable vector"


def test_repeated_failures_back_off(service, monkeypatch):
    """A provider that genuinely cannot embed must not cost a timeout every 2 minutes."""

    class _Dead:
        def encode_many(self, texts, timeout=None):
            return None

    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", lambda provider, model: _Dead())

    service._get_remote()
    first = service._retry_after
    # Not 0.0: `time.monotonic()` counts from boot, so on a freshly started CI
    # runner zero is only seconds ago and the window has not lapsed at all.
    service._remote_failed_at = time.monotonic() - REMOTE_RETRY_MAX_SECONDS - 1
    service._get_remote()
    second = service._retry_after

    assert first == REMOTE_RETRY_SECONDS
    assert second > first, "the retry window must widen after a repeated failure"


def test_the_retry_window_is_measured_after_the_attempt(service, monkeypatch):
    """Stamping it before the probe shortened the window by the cost of the failure.

    A 20s timeout inside a 120s window left 100s, so the expensive failure was
    partly paid for twice.
    """

    class _SlowDead:
        def encode_many(self, texts, timeout=None):
            time.sleep(0.2)
            return None

    monkeypatch.setattr("src.core.embeddings._RemoteEncoder", lambda provider, model: _SlowDead())

    service._get_remote()
    since_failure = time.monotonic() - service._remote_failed_at
    assert since_failure < 0.1, "the clock started before the attempt finished"


def test_a_local_model_that_cannot_encode_is_dropped(service):
    """It was retried on every question, paying for an encoder that always fails."""

    class _Broken:
        def encode(self, texts):
            raise IndexError("list index out of range")

    service._remote = None
    service._model = _Broken()
    service._remote_checked = True
    service._remote_failed_at = time.monotonic()

    first = service.encode_many(["one"])
    assert service._model is None, "a broken encoder must not be kept"

    second = service.encode_many(["one"])
    assert np.allclose(first[0], second[0]), "the fallback must stay stable once adopted"


def test_forced_fallback_never_warms(monkeypatch):
    """Air-gapped installs and the test suite must not reach for a model at all."""
    svc = EmbeddingService(use_fallback=True)
    called = False

    def _explode(provider):
        nonlocal called
        called = True
        return "should-not-happen"

    monkeypatch.setattr(EmbeddingService, "_discover_model", staticmethod(_explode))
    svc.warm(block=True, timeout=2)

    assert called is False
    assert svc.ready is True
    assert svc.backend == "lexical"

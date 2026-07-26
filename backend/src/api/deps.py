"""Shared FastAPI dependencies: session resolution, auth and rate limiting."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Header, HTTPException, Query, Request

from src.config import settings
from src.core.session import Session, session_manager
from src.utils.logging import logger


SESSION_HEADER = "X-Session-Id"


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """No-op unless ``API_KEY`` is configured.

    Local-first deployments stay open by default; anyone exposing the service
    beyond localhost can set a key without touching code. Comparison is constant
    time so the key cannot be recovered by timing.
    """
    if not settings.API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def get_session(
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
    session_query: str | None = Query(default=None, alias="session"),
) -> Session:
    """Resolves the caller's session, creating one when absent or expired."""
    return session_manager.get_or_create(x_session_id or session_query)


def require_session(
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
    session_query: str | None = Query(default=None, alias="session"),
) -> Session:
    """Like :func:`get_session` but rejects an unknown id instead of silently creating one."""
    session_id = x_session_id or session_query
    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired. Create a new session and re-upload your data.",
        )
    return session


def require_dataset(
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
    session_query: str | None = Query(default=None, alias="session"),
) -> Session:
    """Resolves a session that must already have an active dataset."""
    session = get_session(x_session_id, session_query)
    if not session.has_data:
        raise HTTPException(
            status_code=412,
            detail="No dataset loaded. Upload a file before running an analysis.",
        )
    return session


class SlidingWindowRateLimiter:
    """Fixed-memory sliding window keyed by client address.

    The previous limiter kept an unbounded ``defaultdict(list)`` that was never
    swept, so every IP that ever connected stayed resident for the process
    lifetime. This uses bounded deques and evicts idle keys.
    """

    def __init__(self, max_requests: int, window_seconds: int, max_keys: int = 4096):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                return False

            bucket.append(now)

            if len(self._hits) > self.max_keys:
                self._evict_idle(cutoff)
            return True

    def _evict_idle(self, cutoff: float):
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] < cutoff]
        for key in stale:
            del self._hits[key]
        if len(self._hits) > self.max_keys:
            # Still over budget: drop the least recently active keys.
            ordered = sorted(self._hits.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
            for key, _ in ordered[: len(self._hits) - self.max_keys]:
                del self._hits[key]

    def reset(self):
        with self._lock:
            self._hits.clear()


rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


class ConnectionGate:
    """Caps simultaneous WebSocket connections per client.

    HTTP middleware never sees the WebSocket scope, so the old limiter listed
    ``/ws/chat`` in its path set but could not enforce anything there.
    """

    def __init__(self, max_per_key: int):
        self.max_per_key = max_per_key
        self._active: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def acquire(self, key: str) -> bool:
        with self._lock:
            if self._active[key] >= self.max_per_key:
                logger.warning("WebSocket connection rejected, per-client limit reached", client=key)
                return False
            self._active[key] += 1
            return True

    def release(self, key: str):
        with self._lock:
            if self._active.get(key):
                self._active[key] -= 1
                if self._active[key] <= 0:
                    del self._active[key]


ws_gate = ConnectionGate(settings.WS_MAX_CONCURRENT_PER_IP)


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"

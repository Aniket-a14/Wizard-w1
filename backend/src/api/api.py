"""FastAPI application assembly."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.deps import client_key, rate_limiter
from src.api.routes import chat, datasets, meta, sandbox, sessions, workspace
from src.config import settings
from src.core.infra.queue import get_queue
from src.core.session import session_manager
from src.core.tools.sandbox import sandbox_pool
from src.utils.logging import configure_logger, logger


configure_logger()

MAINTENANCE_INTERVAL_SECONDS = 300

# Paths whose cost justifies rate limiting. Read-only routes are excluded so a
# polling UI is never throttled.
RATE_LIMITED_PREFIXES = ("/api/chat", "/api/datasets")


async def _maintenance_loop():
    """Periodically reaps idle sessions and finished jobs."""
    while True:
        try:
            await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
            reaped = await asyncio.to_thread(session_manager.reap_expired)
            pruned = get_queue().prune()
            if reaped or pruned:
                logger.info("Maintenance sweep", sessions_reaped=reaped, jobs_pruned=pruned)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Maintenance sweep failed", error=str(exc))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Starting Wizard backend",
        env=settings.ENV,
        provider=settings.API_PROVIDER,
        sandbox_enabled=settings.SANDBOX_ENABLED,
    )
    # Containers left behind by a previous process would otherwise accumulate.
    await asyncio.to_thread(sandbox_pool.prune_orphans)

    task = asyncio.ensure_future(_maintenance_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await get_queue().shutdown()
        await asyncio.to_thread(session_manager.shutdown)
        await asyncio.to_thread(sandbox_pool.shutdown)
        logger.info("Wizard backend stopped")


app = FastAPI(
    title="Wizard w1",
    description="Local-first autonomous data analysis agent.",
    version=meta.API_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def observability_and_limits(request: Request, call_next):
    """Logs each request and applies the sliding-window rate limit."""
    path = request.url.path

    if any(path.startswith(prefix) for prefix in RATE_LIMITED_PREFIXES) and request.method in {
        "POST",
        "PUT",
        "DELETE",
    }:
        if not rate_limiter.allow(client_key(request)):
            logger.warning("Rate limit exceeded", path=path, client=client_key(request))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment and try again."},
            )

    started = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - started

    logger.info(
        "Request processed",
        method=request.method,
        path=path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Credentials cannot be combined with a wildcard origin; the setting object
    # resolves the two together so the combination is never invalid.
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


app.include_router(meta.router)
app.include_router(sessions.router)
app.include_router(datasets.router)
app.include_router(workspace.router)
app.include_router(sandbox.router)
app.include_router(sandbox.jobs_router)
app.include_router(chat.router)


__all__ = ["app"]

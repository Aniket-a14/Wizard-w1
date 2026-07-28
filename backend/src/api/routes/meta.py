"""Health, capability discovery and model selection."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_session, require_api_key
from src.api.schemas import (
    HealthResponse,
    ModelDownloadRequest,
    ModelDownloadsResponse,
    ModelDownloadState,
    ModelListResponse,
    ModelSelection,
    ProviderDownloadCapability,
    ServerConfig,
    SessionResponse,
)
from src.config import settings
from src.core.embeddings import embedding_service
from src.core.infra.cache import get_cache
from src.core.infra.queue import get_queue
from src.core.ingest.documents import supported_document_extensions
from src.core.ingest.loader import DatasetLoader
from src.core.llm import llm_provider, model_registry
from src.core.llm.downloader import ProviderNotDownloadable, model_downloader
from src.core.session import Session
from src.core.tools import runtime as runtime_backend
from src.utils.hostinfo import host_info


router = APIRouter(tags=["meta"])

API_VERSION = "3.1.0"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    backend = runtime_backend.active_backend()
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        sandbox_available=backend == "docker",
        execution_backend=backend,
        model_provider=settings.API_PROVIDER,
    )


@router.get("/api/config", response_model=ServerConfig)
async def server_config() -> ServerConfig:
    """Everything the client needs to render the right controls."""
    host = host_info()
    backend = runtime_backend.active_backend()
    return ServerConfig(
        app_name=settings.APP_NAME,
        version=API_VERSION,
        plot_format=settings.PLOT_FORMAT,
        sandbox_available=backend == "docker",
        sandbox_enabled=settings.SANDBOX_ENABLED,
        execution_backend=backend,
        execution_backend_setting=settings.EXECUTION_BACKEND,
        sandbox_tier=settings.SANDBOX_TIER,
        system_profile=settings.system_profile,
        host_cores=host.cores,
        host_ram_gb=None if host.ram_gb is None else round(host.ram_gb, 1),
        sandbox_mem_limit=settings.SANDBOX_MEM_LIMIT,
        max_sessions=settings.SESSION_MAX_ACTIVE,
        model_provider=settings.API_PROVIDER,
        supported_formats=DatasetLoader.supported_extensions(),
        max_upload_mb=settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        queue_backend=get_queue().backend_name,
        cache_backend=get_cache().name,
        embeddings_semantic=embedding_service.is_semantic,
        embeddings_backend=embedding_service.backend,
        rag_enabled=settings.RAG_ENABLED,
        council_enabled=settings.COUNCIL_ENABLED,
        requires_api_key=bool(settings.API_KEY),
        agent_tier=settings.AGENT_TIER,
        agent_max_iterations=settings.AGENT_MAX_ITERATIONS,
        agent_require_approval=settings.AGENT_REQUIRE_APPROVAL,
        agent_verify=settings.AGENT_VERIFY,
        agent_grounding_check=settings.AGENT_GROUNDING_CHECK,
        context_docs_enabled=settings.CONTEXT_DOCS_ENABLED,
        supported_document_formats=supported_document_extensions(),
    )


@router.get("/api/models", response_model=ModelListResponse)
async def list_models(
    refresh: bool = False,
    provider: str | None = None,
    session: Session = Depends(get_session),
) -> ModelListResponse:
    """Models installed on one provider, so the user can actually pick one.

    ``provider`` selects which backend to enumerate. Discovery talks to a
    possibly-unreachable host, so it runs off the event loop.
    """
    resolved = settings.resolve_provider(provider)
    models = await asyncio.to_thread(model_registry.list_models, refresh, resolved)
    suggested = await asyncio.to_thread(model_registry.suggest, resolved)

    return ModelListResponse(
        provider=resolved,
        models=[model.to_dict() for model in models],
        suggested=suggested,
        selected={
            # Falls back to what discovery resolved, not to the configured
            # default -- that is empty now, and reporting "" as the selected
            # model would leave the picker showing nothing while the run used
            # something real.
            "manager": session.models.manager or settings.MODEL_NAME or suggested.get("manager"),
            "worker": session.models.worker or settings.WORKER_MODEL_NAME or suggested.get("worker"),
            "vision": session.models.vision or settings.VISION_MODEL_NAME or suggested.get("vision"),
            "temperature": session.models.temperature
            if session.models.temperature is not None
            else settings.TEMPERATURE,
            "manager_provider": session.models.manager_provider or settings.API_PROVIDER,
            "worker_provider": session.models.worker_provider or settings.API_PROVIDER,
            "vision_provider": session.models.vision_provider or settings.API_PROVIDER,
        },
        providers=model_registry.available_providers(),
        error=model_registry.error_for(resolved) if not models else None,
    )


@router.get("/api/models/downloads", response_model=ModelDownloadsResponse)
async def list_downloads(provider: str | None = None) -> ModelDownloadsResponse:
    """In-flight and just-finished installs, plus whether this provider allows them.

    Polled by the client while a download runs. Every download is listed
    regardless of ``provider`` — a pull started on one provider must stay
    visible after the picker is switched to another, or it looks abandoned.
    """
    return ModelDownloadsResponse(
        downloads=[ModelDownloadState(**entry) for entry in model_downloader.list()],
        capability=ProviderDownloadCapability(**model_downloader.capability(provider)),
    )


@router.post(
    "/api/models/download",
    response_model=ModelDownloadState,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def download_model(request: ModelDownloadRequest) -> ModelDownloadState:
    """Starts installing a model. Returns immediately; poll ``/api/models/downloads``."""
    try:
        state = model_downloader.start(request.provider, request.model)
    except ProviderNotDownloadable as exc:
        # Not the caller's mistake — the provider or the machine cannot do this.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelDownloadState(**state.to_dict())


@router.post("/api/models/download/cancel", dependencies=[Depends(require_api_key)])
async def cancel_download(request: ModelDownloadRequest) -> dict:
    cancelled = await asyncio.to_thread(model_downloader.cancel, request.provider, request.model)
    return {"status": "cancelling" if cancelled else "not_running"}


@router.delete("/api/models/installed", dependencies=[Depends(require_api_key)])
async def delete_model(model: str, provider: str | None = None) -> dict:
    """Removes an installed model. Ollama only — LM Studio's CLI has no delete."""
    try:
        await asyncio.to_thread(model_downloader.remove, provider, model)
    except ProviderNotDownloadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface the provider's own words
        raise HTTPException(status_code=502, detail=f"Could not delete {model}: {exc}") from exc
    return {"status": "deleted", "model": model}


@router.post("/api/models", response_model=SessionResponse, dependencies=[Depends(require_api_key)])
async def select_models(selection: ModelSelection, session: Session = Depends(get_session)) -> SessionResponse:
    """Sets this session's preferred models. Unspecified fields keep their value."""
    for role in ("manager", "worker", "vision"):
        model = getattr(selection, role)
        provider = getattr(selection, f"{role}_provider")
        if model is not None:
            setattr(session.models, role, model or None)
        if provider is not None:
            setattr(session.models, f"{role}_provider", provider or None)
            # A provider switch without a model name would otherwise send the
            # previous backend's model id to the new one, and an Ollama tag is a
            # 404 on LM Studio. Resolve a real default from what that provider
            # actually has.
            if model is None:
                suggested = await asyncio.to_thread(model_registry.suggest, provider)
                setattr(session.models, role, suggested.get(role))

    if selection.temperature is not None:
        session.models.temperature = selection.temperature

    # Clients are keyed by spec, so a changed temperature must not reuse a warm client.
    llm_provider.clear_cache()
    return SessionResponse(**session.describe())

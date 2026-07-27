"""Health, capability discovery and model selection."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from src.api.deps import get_session, require_api_key
from src.api.schemas import (
    HealthResponse,
    ModelListResponse,
    ModelSelection,
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
from src.core.session import Session
from src.core.tools.sandbox import sandbox_pool


router = APIRouter(tags=["meta"])

API_VERSION = "3.0.0"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        sandbox_available=sandbox_pool.available,
        model_provider=settings.API_PROVIDER,
    )


@router.get("/api/config", response_model=ServerConfig)
async def server_config() -> ServerConfig:
    """Everything the client needs to render the right controls."""
    return ServerConfig(
        app_name=settings.APP_NAME,
        version=API_VERSION,
        plot_format=settings.PLOT_FORMAT,
        sandbox_available=sandbox_pool.available,
        sandbox_enabled=settings.SANDBOX_ENABLED,
        model_provider=settings.API_PROVIDER,
        supported_formats=DatasetLoader.supported_extensions(),
        max_upload_mb=settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        queue_backend=get_queue().backend_name,
        cache_backend=get_cache().name,
        embeddings_semantic=embedding_service.is_semantic,
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

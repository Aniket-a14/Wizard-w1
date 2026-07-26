"""Health, capability discovery and model selection."""

from __future__ import annotations

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
    )


@router.get("/api/models", response_model=ModelListResponse)
async def list_models(refresh: bool = False, session: Session = Depends(get_session)) -> ModelListResponse:
    """Models installed on the configured host, so the user can actually pick one."""
    models = model_registry.list_models(force=refresh)
    return ModelListResponse(
        provider=settings.API_PROVIDER,
        models=[model.to_dict() for model in models],
        suggested=model_registry.suggest(),
        selected={
            "manager": session.models.manager or settings.MODEL_NAME,
            "worker": session.models.worker or settings.WORKER_MODEL_NAME,
            "vision": session.models.vision or settings.VISION_MODEL_NAME,
            "temperature": session.models.temperature
            if session.models.temperature is not None
            else settings.TEMPERATURE,
        },
        error=model_registry.last_error if not models else None,
    )


@router.post("/api/models", response_model=SessionResponse, dependencies=[Depends(require_api_key)])
async def select_models(selection: ModelSelection, session: Session = Depends(get_session)) -> SessionResponse:
    """Sets this session's preferred models. Unspecified fields keep their value."""
    if selection.manager is not None:
        session.models.manager = selection.manager or None
    if selection.worker is not None:
        session.models.worker = selection.worker or None
    if selection.vision is not None:
        session.models.vision = selection.vision or None
    if selection.temperature is not None:
        session.models.temperature = selection.temperature

    # Clients are keyed by spec, so a changed temperature must not reuse a warm client.
    llm_provider.clear_cache()
    return SessionResponse(**session.describe())

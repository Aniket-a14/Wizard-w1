"""Request and response models for the HTTP surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    detail: Any


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    sandbox_available: bool
    model_provider: str


class ServerConfig(BaseModel):
    """Capabilities the client uses to decide what UI to show."""

    app_name: str
    version: str
    plot_format: Literal["png", "html"]
    sandbox_available: bool
    sandbox_enabled: bool
    model_provider: str
    supported_formats: list[str]
    max_upload_mb: int
    queue_backend: str
    cache_backend: str
    embeddings_semantic: bool
    rag_enabled: bool
    council_enabled: bool
    requires_api_key: bool


class SessionResponse(BaseModel):
    session_id: str
    created_at: float
    last_seen: float
    has_data: bool
    active_dataset: str | None = None
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    models: dict[str, Any] = Field(default_factory=dict)
    sandboxed: bool = False


class ModelInfoResponse(BaseModel):
    name: str
    size_bytes: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    capabilities: list[str] = Field(default_factory=list)
    installed: bool = True


class ModelListResponse(BaseModel):
    provider: str
    models: list[ModelInfoResponse]
    suggested: dict[str, str | None]
    selected: dict[str, Any]
    error: str | None = None


class ModelSelection(BaseModel):
    manager: str | None = Field(default=None, max_length=200)
    worker: str | None = Field(default=None, max_length=200)
    vision: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class DatasetSummary(BaseModel):
    name: str
    rows: int
    columns: list[str]
    column_count: int
    source_format: str
    profile: dict[str, Any] = Field(default_factory=dict)
    loaded_at: float


class UploadResponse(BaseModel):
    message: str
    dataset: DatasetSummary
    cleaning_result: str
    warnings: list[str] = Field(default_factory=list)
    catalog: dict[str, Any] = Field(default_factory=dict)
    session_id: str


class PreviewResponse(BaseModel):
    page: int
    per_page: int
    total_rows: int
    total_pages: int
    columns: list[str]
    data: list[dict[str, Any]]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    mode: Literal["planning", "fast"] = "planning"
    approved_plan: str | None = Field(default=None, max_length=20000)


class ChatResponse(BaseModel):
    response: str
    code: str = ""
    thought: str | None = None
    plan: str | None = None
    image: str | None = None
    status: str = "completed"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    approval: dict[str, Any] | None = None
    downloads: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


class WorkspaceFile(BaseModel):
    name: str
    path: str
    size: int
    type: str
    modified_at: float


class WorkspaceListing(BaseModel):
    files: list[WorkspaceFile]


class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    result: Any = None


class ReportResponse(BaseModel):
    report: str
    interaction_count: int


class VariablesResponse(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    sandbox_available: bool = False

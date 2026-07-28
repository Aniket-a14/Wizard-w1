"""Request and response models for the HTTP surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.config import Provider


# Rejecting an unknown provider at the schema boundary means the session can
# never hold a value the LLM layer would silently fall back on.
ProviderName = Provider


class ErrorDetail(BaseModel):
    detail: Any


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    sandbox_available: bool
    execution_backend: str = "inprocess"
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
    #: What actually produces vectors: "provider:<model>", "local:<model>" or
    #: "lexical". `embeddings_semantic` alone could not distinguish a provider
    #: embedding model from an in-process one, and the two fail differently.
    embeddings_backend: str = "lexical"
    rag_enabled: bool
    council_enabled: bool
    requires_api_key: bool
    # How the agentic loop is configured. The client shows these read-only —
    # they come from backend/.env and changing one needs a restart.
    agent_tier: str = "auto"
    agent_max_iterations: int = 24
    agent_require_approval: bool = False
    agent_verify: bool = True
    agent_grounding_check: bool = True
    context_docs_enabled: bool = True
    supported_document_formats: list[str] = Field(default_factory=list)
    agent_turn_timeout: float = 300.0
    # What local inference was actually configured with. These are derived from
    # the machine unless pinned, and getting them wrong is the usual reason a
    # question is slow — so they are shown rather than left in a file.
    llm_num_thread: int = 0
    llm_num_ctx: int = 0
    llm_keep_alive: str = ""
    #: Settings that will make this install slow, in plain language. Empty when
    #: there is nothing to say, which is the common case.
    performance_notes: list[str] = Field(default_factory=list)
    # Where generated code runs, and on what machine. `sandbox_available` says
    # only whether Docker answered; these say what is actually in use.
    execution_backend: Literal["docker", "local", "inprocess"] = "inprocess"
    execution_backend_setting: str = "auto"
    sandbox_tier: str = "standard"
    system_profile: str = "server"
    host_cores: int = 0
    host_ram_gb: float | None = None
    sandbox_mem_limit: str = ""
    max_sessions: int = 0


class SessionResponse(BaseModel):
    session_id: str
    created_at: float
    last_seen: float
    has_data: bool
    active_dataset: str | None = None
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    models: dict[str, Any] = Field(default_factory=dict)
    #: True only for a container. A local runtime is isolated from the API
    #: process but is not a security boundary, so it does not claim to be one.
    sandboxed: bool = False
    execution_backend: str = "inprocess"


class ModelInfoResponse(BaseModel):
    name: str
    size_bytes: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    capabilities: list[str] = Field(default_factory=list)
    installed: bool = True
    provider: str = ""
    context_length: int = 0
    loaded: bool | None = None


class ProviderInfo(BaseModel):
    id: str
    base_url: str = ""
    configured: bool = False
    local: bool = False
    is_default: bool = False


class ModelListResponse(BaseModel):
    provider: str
    models: list[ModelInfoResponse]
    suggested: dict[str, str | None]
    selected: dict[str, Any]
    providers: list[ProviderInfo] = Field(default_factory=list)
    error: str | None = None


class ModelDownloadRequest(BaseModel):
    """A model to install. ``provider`` defaults to the configured one."""

    model: str = Field(min_length=1, max_length=200)
    provider: ProviderName | None = None


class ModelDownloadState(BaseModel):
    provider: str
    model: str
    status: Literal["queued", "downloading", "completed", "failed", "cancelled"]
    completed_bytes: int = 0
    total_bytes: int = 0
    #: None when the provider reports no measurable progress — LM Studio says
    #: nothing at all while it resolves a repo, and a bar stuck at 0% reads as
    #: broken where "Resolving" does not.
    percent: float | None = None
    detail: str = ""
    error: str | None = None
    started_at: float
    finished_at: float | None = None


class ProviderDownloadCapability(BaseModel):
    """Whether models can be installed from here, and the reason when not."""

    provider: str
    can_download: bool = False
    can_delete: bool = False
    reason: str = ""


class ModelDownloadsResponse(BaseModel):
    downloads: list[ModelDownloadState] = Field(default_factory=list)
    capability: ProviderDownloadCapability


class ModelSelection(BaseModel):
    manager: str | None = Field(default=None, max_length=200)
    worker: str | None = Field(default=None, max_length=200)
    vision: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    manager_provider: ProviderName | None = None
    worker_provider: ProviderName | None = None
    vision_provider: ProviderName | None = None


class DatasetSummary(BaseModel):
    name: str
    #: How generated code addresses this table: `tables['<table_key>']`.
    table_key: str = ""
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


#: ``auto`` lets the agent choose its own depth, ``fast`` forces a single shot,
#: ``deep`` forces a full investigation. ``planning`` is the legacy name for
#: "investigate, but let me approve the plan first" and is kept so existing
#: clients and stored sessions keep working.
AnalysisMode = Literal["auto", "fast", "deep", "planning"]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    mode: AnalysisMode = "auto"
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
    # What the investigation established, and how far it was trusted.
    findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    iterations: int = 0
    tier: str = "balanced"
    mode: str = "auto"
    verification: str = ""
    grounding: dict[str, Any] = Field(default_factory=dict)


class DocumentSummary(BaseModel):
    name: str
    chars: int
    chunks: int
    source_format: str
    preview: str = ""


class DocumentUploadResponse(BaseModel):
    message: str
    document: DocumentSummary
    session_id: str


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

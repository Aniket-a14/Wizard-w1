from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Every backend the runtime can talk to. "ollama" and "lmstudio" are local
# daemons; the other two are OpenAI-compatible endpoints reached over HTTP.
Provider = Literal["ollama", "lmstudio", "openai", "custom_gateway"]

PROVIDERS: tuple[str, ...] = ("ollama", "lmstudio", "openai", "custom_gateway")

# Providers whose model list can be enumerated without the user configuring a
# URL first, and which therefore always appear in the picker.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio"})


# How the agentic loop is sized for the model actually behind it.
#
# The loop asks a model to choose its next action from real execution output.
# A frontier model does that well and is worth giving a long leash; a 1.5B local
# model does it badly and every extra iteration is another chance to wander, so
# it gets a short budget, a smaller action menu and deterministic fallbacks.
# One codebase, three shapes -- rather than three code paths.
AgentTier = Literal["compact", "balanced", "full"]


@dataclass(frozen=True)
class TierBudget:
    """Per-tier limits for one analysis turn."""

    #: Which tier produced this budget. Carried on the object so callers can
    #: report it without reverse-matching the numbers back to a tier.
    tier: str
    #: Iterations allowed in `auto` mode before the agent must answer.
    iterations: int
    #: Iterations allowed when the user explicitly asks for a deep run.
    deep_iterations: int
    #: Columns of schema detail spent per prompt.
    max_columns: int
    #: Retrieved context-document chunks injected per decision.
    doc_chunks: int
    #: Whether the agent may spend a whole iteration on reflection alone.
    #: Small models reliably waste it restating the question.
    allow_reflection: bool
    #: Whether verification re-derives the result with a second execution.
    allow_verification: bool
    #: Characters of prior-step output carried into the next decision.
    observation_chars: int


TIER_BUDGETS: dict[str, TierBudget] = {
    "compact": TierBudget(
        tier="compact",
        iterations=4,
        deep_iterations=6,
        max_columns=25,
        doc_chunks=2,
        allow_reflection=False,
        allow_verification=False,
        observation_chars=1500,
    ),
    "balanced": TierBudget(
        tier="balanced",
        iterations=8,
        deep_iterations=14,
        max_columns=60,
        doc_chunks=4,
        allow_reflection=True,
        allow_verification=True,
        observation_chars=4000,
    ),
    "full": TierBudget(
        tier="full",
        iterations=12,
        deep_iterations=24,
        max_columns=120,
        doc_chunks=6,
        allow_reflection=True,
        allow_verification=True,
        observation_chars=8000,
    ),
}

# Below this many billions of parameters a model cannot be trusted to steer its
# own multi-step investigation. The boundary is drawn between the 3B and 7B
# classes because that is where instruction-following on structured action
# selection becomes reliable enough to be worth the round-trip.
COMPACT_MAX_PARAMS_B = 4.0
FULL_MIN_PARAMS_B = 30.0


def tier_for_parameter_size(parameter_size: str | None) -> AgentTier:
    """Maps a reported parameter count ("1.5B", "7B", "70B") onto a tier.

    Returns ``"balanced"`` for anything unparseable, which is every hosted
    gateway model -- they do not report a size and are not small.
    """
    if not parameter_size:
        return "balanced"
    cleaned = str(parameter_size).strip().upper().rstrip("B")
    try:
        billions = float(cleaned)
    except ValueError:
        return "balanced"
    if billions <= 0:
        return "balanced"
    if billions < COMPACT_MAX_PARAMS_B:
        return "compact"
    if billions >= FULL_MIN_PARAMS_B:
        return "full"
    return "balanced"


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent

    # Adaptive Hardware Profile
    SYSTEM_PROFILE: Literal["laptop", "server", "hpc"] = "laptop"

    # Model Configuration
    # NOTE: MODEL_TYPE is retained only so existing .env files keep validating.
    # API_PROVIDER is the value the runtime actually branches on, and it is only
    # the *default*: a session may pick a different provider per role.
    #
    # The three role models default to EMPTY, which means "use whatever this
    # provider actually has installed", resolved through `model_registry`.
    # Naming a model here pins it as an override. They were previously hardcoded
    # to specific Ollama tags, which made those two models load-bearing: the tag
    # is a 404 on LM Studio or any gateway, and a fresh install with different
    # models pulled would fail on the first request with an opaque error.
    MODEL_TYPE: Provider = "ollama"
    MODEL_NAME: str = ""
    WORKER_MODEL_NAME: str = ""
    VISION_MODEL_NAME: str = ""
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    FEEDBACK_FILE: str = "feedback_data.json"

    # LM Studio. Stored as a bare root because two API surfaces hang off it:
    # `/v1` (OpenAI-compatible, used for inference) and `/api/v0` (native, used
    # for discovery -- it reports real capabilities and load state).
    # LM Studio binds loopback only by default; enable "Serve on Local Network"
    # for the backend container to reach the host.
    LMSTUDIO_BASE_URL: str = "http://host.docker.internal:1234"
    LMSTUDIO_API_KEY: str = ""  # LM Studio ignores it; present for proxies that don't

    # Sandbox
    SANDBOX_NETWORK_DISABLED: bool = False
    SANDBOX_DOCKER_RUNTIME: str = ""
    SANDBOX_MEM_LIMIT: str = "2g"
    SANDBOX_CPU_QUOTA: int = 0  # 0 = unlimited; 100000 == 1 CPU
    SANDBOX_PIDS_LIMIT: int = 256
    SANDBOX_EXEC_TIMEOUT: int = 180  # seconds per code execution
    SANDBOX_ALLOW_RUNTIME_PIP: bool = True
    # When False the sandbox container is never created (unit tests / CI / no Docker host).
    SANDBOX_ENABLED: bool = True

    # Enterprise / Cloud API Provider Config
    API_PROVIDER: Provider = "ollama"
    GATEWAY_API_URL: str = ""
    GATEWAY_API_KEY: str = ""
    PLOT_FORMAT: Literal["png", "html"] = "html"

    # Analysis Configuration
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.0
    LLM_NUM_CTX: int = 16384
    LLM_NUM_THREAD: int = 8
    LLM_REQUEST_TIMEOUT: int = 300
    MAX_CORRECTION_RETRIES: int = 3

    # ------------------------------------------------------------------ #
    # Agentic loop
    #
    # The analysis is an observe -> decide -> act loop, not a fixed pipeline:
    # the agent sees real execution output and revises what it does next. That
    # is the only shape that answers questions needing several dependent steps,
    # but it costs one manager round-trip per iteration -- so every budget here
    # is scaled by the tier, which is what lets the same code run on a 1.5B
    # local model and on a frontier gateway.
    # ------------------------------------------------------------------ #
    AGENT_TIER: Literal["auto", "compact", "balanced", "full"] = "auto"
    # Hard ceiling regardless of tier or mode. A runaway loop on a paid gateway
    # is a billing incident, so this is deliberately not derived.
    AGENT_MAX_ITERATIONS: int = 24
    # How much of one execution's stdout is fed back into the next decision.
    # The old pipeline passed 200 characters between steps, which silently threw
    # away every intermediate result a later step depended on.
    AGENT_OBSERVATION_CHARS: int = 4000
    # Halt for plan approval before anything runs. Off by default: an agent that
    # asks permission for every question is not autonomous. Web search always
    # asks regardless, because that leaves the machine.
    AGENT_REQUIRE_APPROVAL: bool = False
    # Re-derive the headline result a second way before answering.
    AGENT_VERIFY: bool = True
    # Refuse to present numbers that never appeared in real execution output.
    AGENT_GROUNDING_CHECK: bool = True
    # Emit a reproducible standalone script for each completed analysis.
    AGENT_EMIT_SCRIPT: bool = True

    # Council review (each specialist costs an LLM round-trip)
    COUNCIL_ENABLED: bool = True
    COUNCIL_TIMEOUT: float = 20.0
    VISION_ENABLED: bool = False

    # ------------------------------------------------------------------ #
    # Context documents
    #
    # Hard analytical questions are rarely answerable from the tables alone --
    # they turn on a data dictionary, a fee schedule, a metric definition. These
    # are ingested alongside the datasets, chunked, and retrieved during a run.
    # ------------------------------------------------------------------ #
    CONTEXT_DOCS_ENABLED: bool = True
    CONTEXT_DOC_MAX_BYTES: int = 32 * 1024 * 1024
    CONTEXT_CHUNK_CHARS: int = 1200
    CONTEXT_CHUNK_OVERLAP: int = 150
    CONTEXT_TOP_K: int = 5

    # Ingestion limits
    MAX_UPLOAD_BYTES: int = 512 * 1024 * 1024  # 512MB on disk
    MAX_INMEMORY_ROWS: int = 2_000_000
    PROFILE_SAMPLE_ROWS: int = 200_000  # rows used for profiling/catalog on big data
    PROMPT_MAX_COLUMNS: int = 60  # wide-frame guard for prompt context

    # Sessions
    SESSION_TTL_SECONDS: int = 60 * 60 * 6
    SESSION_MAX_ACTIVE: int = 32
    SESSION_HISTORY_TURNS: int = 8

    # Retrieval / RAG
    # Skips the sentence-transformers download entirely and uses the hashing
    # encoder. Needed for air-gapped installs and for CI, where a per-run model
    # download is both slow and a network-flakiness dependency.
    EMBEDDINGS_FORCE_FALLBACK: bool = False
    RAG_ENABLED: bool = True
    RAG_TOP_K: int = 4
    RAG_MIN_SIMILARITY: float = 0.35
    SEMANTIC_CACHE_THRESHOLD: float = 0.92
    TRAJECTORY_MIN_SIMILARITY: float = 0.90

    # Queue / cache backends. Redis is entirely optional: when REDIS_URL is empty
    # (or the redis package is missing) an in-process implementation is used.
    REDIS_URL: str = ""
    QUEUE_MAX_WORKERS: int = 2
    JOB_RESULT_TTL_SECONDS: int = 3600

    # HTTP / transport security
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    API_KEY: str = ""  # when set, every mutating route requires X-API-Key
    RATE_LIMIT_MAX_REQUESTS: int = 60
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    WS_MAX_CONCURRENT_PER_IP: int = 4

    # Paths
    DATA_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "data")
    LOG_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    WORKSPACE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent / "workspace")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("CORS_ALLOW_ORIGINS")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @field_validator("LMSTUDIO_BASE_URL")
    @classmethod
    def _normalize_lmstudio_url(cls, value: str) -> str:
        # LM Studio's own UI displays the endpoint as ".../v1", so that is what
        # people paste. Discovery needs the root, so accept either form.
        cleaned = value.strip().rstrip("/")
        if cleaned.endswith("/v1"):
            cleaned = cleaned[: -len("/v1")]
        return cleaned

    # ------------------------------------------------------------------ #
    # Provider resolution
    #
    # A session may run each role on a different backend, so nothing may read
    # a provider's URL directly -- it has to go through these, keyed by the
    # provider actually in play for that call.
    # ------------------------------------------------------------------ #
    def resolve_provider(self, provider: str | None = None) -> str:
        """Falls back to the configured default for an empty or unknown value."""
        candidate = (provider or "").strip().lower()
        return candidate if candidate in PROVIDERS else self.API_PROVIDER

    def provider_root_url(self, provider: str | None = None) -> str:
        """Root URL of the daemon, with no API-version suffix."""
        name = self.resolve_provider(provider)
        if name == "ollama":
            return self.OLLAMA_BASE_URL.rstrip("/")
        if name == "lmstudio":
            return self.LMSTUDIO_BASE_URL.rstrip("/")
        return self.GATEWAY_API_URL.rstrip("/")

    def provider_openai_base_url(self, provider: str | None = None) -> str:
        """The `/v1` base an OpenAI-compatible client should be pointed at."""
        name = self.resolve_provider(provider)
        root = self.provider_root_url(name)
        if name == "lmstudio":
            return f"{root}/v1"
        # A gateway URL is configured by hand and already includes its version
        # segment, so appending one here would break every existing install.
        return root

    def provider_api_key(self, provider: str | None = None) -> str:
        name = self.resolve_provider(provider)
        if name == "lmstudio":
            return self.LMSTUDIO_API_KEY
        return self.GATEWAY_API_KEY

    def provider_is_configured(self, provider: str | None = None) -> bool:
        """Whether this provider has somewhere to connect to."""
        name = self.resolve_provider(provider)
        if name in LOCAL_PROVIDERS:
            return bool(self.provider_root_url(name))
        return bool(self.GATEWAY_API_URL.strip())

    # ------------------------------------------------------------------ #
    # Agent budgeting
    # ------------------------------------------------------------------ #
    def resolve_tier(self, parameter_size: str | None = None) -> AgentTier:
        """The tier to run this turn at.

        An explicit ``AGENT_TIER`` always wins. On ``auto`` the tier is inferred
        from the manager model's reported parameter count, which is the only
        signal available without benchmarking: Ollama reports it per tag, LM
        Studio reports it per model, and hosted gateways report nothing -- for
        which ``balanced`` is the right assumption.
        """
        if self.AGENT_TIER != "auto":
            return self.AGENT_TIER  # type: ignore[return-value]
        return tier_for_parameter_size(parameter_size)

    def budget_for(self, mode: str = "auto", parameter_size: str | None = None) -> TierBudget:
        """Concrete limits for one turn, given the mode and the model behind it."""
        tier = self.resolve_tier(parameter_size)
        budget = TIER_BUDGETS[tier]

        if mode == "fast":
            # One shot: write code, run it, answer. No investigation, and no
            # verification either -- a second execution plus an extra worker
            # round-trip is the single most expensive thing the turn could do,
            # and the user asking for `fast` has said they do not want it.
            return replace(
                budget,
                iterations=1,
                allow_reflection=False,
                allow_verification=False,
                observation_chars=min(budget.observation_chars, self.AGENT_OBSERVATION_CHARS),
            )

        iterations = budget.deep_iterations if mode == "deep" else budget.iterations
        return replace(
            budget,
            iterations=min(iterations, self.AGENT_MAX_ITERATIONS),
            observation_chars=min(budget.observation_chars, self.AGENT_OBSERVATION_CHARS),
        )

    @property
    def cors_origins(self) -> list[str]:
        """Parsed CORS allowlist. `*` is honoured but disables credentialed requests."""
        raw = [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",")]
        return [origin for origin in raw if origin]

    @property
    def cors_allow_credentials(self) -> bool:
        # Sending credentials with a wildcard origin is rejected by every browser
        # and is a spec violation, so the two settings are resolved here once.
        return "*" not in self.cors_origins

    @property
    def redis_enabled(self) -> bool:
        return bool(self.REDIS_URL.strip())


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

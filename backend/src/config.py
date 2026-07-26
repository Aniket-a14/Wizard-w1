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
    MODEL_TYPE: Provider = "ollama"
    MODEL_NAME: str = "deepseek-r1:1.5b"
    WORKER_MODEL_NAME: str = "qwen2.5-coder:1.5b"
    VISION_MODEL_NAME: str = "llava:7b"
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

    # Council review (each specialist costs an LLM round-trip)
    COUNCIL_ENABLED: bool = True
    COUNCIL_TIMEOUT: float = 20.0
    VISION_ENABLED: bool = False

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

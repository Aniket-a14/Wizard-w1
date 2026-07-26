from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent

    # Adaptive Hardware Profile
    SYSTEM_PROFILE: Literal["laptop", "server", "hpc"] = "laptop"

    # Model Configuration
    # NOTE: MODEL_TYPE is retained only so existing .env files keep validating.
    # API_PROVIDER is the value the runtime actually branches on.
    MODEL_TYPE: Literal["ollama", "openai", "custom_gateway"] = "ollama"
    MODEL_NAME: str = "deepseek-r1:1.5b"
    WORKER_MODEL_NAME: str = "qwen2.5-coder:1.5b"
    VISION_MODEL_NAME: str = "llava:7b"
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    FEEDBACK_FILE: str = "feedback_data.json"

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
    API_PROVIDER: Literal["ollama", "openai", "custom_gateway"] = "ollama"
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

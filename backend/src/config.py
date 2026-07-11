from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent

    # Adaptive Hardware Profile
    SYSTEM_PROFILE: Literal["laptop", "server", "hpc"] = "laptop"

    # Model Configuration
    MODEL_TYPE: Literal["ollama", "openai", "custom_gateway"] = "ollama"
    MODEL_NAME: str = "deepseek-r1:1.5b"
    WORKER_MODEL_NAME: str = "qwen2.5-coder:1.5b"
    VISION_MODEL_NAME: str = "llava:7b"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    FEEDBACK_FILE: str = "feedback_data.json"
    SANDBOX_NETWORK_DISABLED: bool = False
    SANDBOX_DOCKER_RUNTIME: str = ""

    # Enterprise / Cloud API Provider Config
    API_PROVIDER: Literal["ollama", "openai", "custom_gateway"] = "ollama"
    GATEWAY_API_URL: str = ""
    GATEWAY_API_KEY: str = ""
    PLOT_FORMAT: Literal["png", "html"] = "html"

    # Analysis Configuration
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.0
    LLM_NUM_CTX: int = 4096
    LLM_NUM_THREAD: int = 8

    # Paths
    DATA_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "data")
    LOG_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    WORKSPACE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent / "workspace")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

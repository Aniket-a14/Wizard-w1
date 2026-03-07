from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
from typing import Literal


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent
    
    # Adaptive Hardware Profile
    SYSTEM_PROFILE: Literal["laptop", "server", "hpc"] = "laptop"

    # Model Configuration
    MODEL_TYPE: Literal["ollama"] = "ollama"
    MODEL_NAME: str = "deepseek-r1:1.5b"
    WORKER_MODEL_NAME: str = "qwen2.5-coder:1.5b"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OFFLOAD_FOLDER: str = "offload"
    FEEDBACK_FILE: str = "feedback_data.json"



    # Analysis Configuration
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.0
    LLM_NUM_CTX: int = 4096
    LLM_NUM_THREAD: int = 8

    # Paths
    DATA_DIR: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent / "data"
    )
    LOG_DIR: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent / "logs"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

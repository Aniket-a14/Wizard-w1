from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
from typing import Literal


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent

    # Model Configuration
    MODEL_TYPE: Literal["ollama", "local", "hybrid"] = "hybrid"
    MODEL_NAME: str = "deepseek-r1"  # For Ollama (Deprecated/Fallback)
    MODEL_PATH: str = "./models/worker_base"  # For Local Worker
    MANAGER_MODEL_PATH: str = "./models/manager"  # For Local Manager (DeepSeek)

    @property
    def resolved_model_path(self) -> Path:
        """Resolve model path relative to BASE_DIR if not absolute."""
        path = Path(self.MODEL_PATH)
        if path.is_absolute():
            return path
        return self.BASE_DIR / path

    # Analysis Configuration
    MAX_TOKENS: int = 2000
    TEMPERATURE: float = 0.7

    # Paths
    DATA_DIR: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent / "data"
    )
    LOG_DIR: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent / "logs"
    )

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

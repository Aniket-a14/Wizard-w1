from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings using Pydantic Settings."""
    
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Wizard Data Analyst"
    
    # Model Configuration
    # Model Configuration
    MODEL_TYPE: Literal['ollama', 'local', 'hybrid'] = 'local'
    MODEL_NAME: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    MODEL_PATH: str = "./backend/fine_tuned_model"
    
    # Security (Defaults should be overridden in .env for production)
    SECRET_KEY: str = "development_secret_key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

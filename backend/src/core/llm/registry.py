"""Discovery of models the user can actually pick.

"Local first, user chooses their model" only works if the UI can find out what
is installed. This queries the Ollama daemon's ``/api/tags`` endpoint (or the
gateway's ``/v1/models``) and classifies each result so the frontend can suggest
sensible defaults per role rather than presenting an undifferentiated list.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from src.config import settings
from src.utils.logging import logger


CACHE_TTL_SECONDS = 30

# Substrings that indicate a model is specialised. Ordered by specificity.
CODE_HINTS = ("coder", "code", "starcoder", "deepseek-coder", "codellama", "codegemma", "qwen2.5-coder")
REASONING_HINTS = ("r1", "reason", "think", "qwq", "o1", "phi-4", "marco")
VISION_HINTS = ("llava", "vision", "bakllava", "moondream", "minicpm-v", "gemma3", "pixtral")
EMBED_HINTS = ("embed", "bge", "minilm", "nomic", "mxbai", "gte")


@dataclass
class ModelInfo:
    name: str
    size_bytes: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    capabilities: list[str] = field(default_factory=list)
    installed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(name: str) -> list[str]:
    """Best-effort capability tags derived from the model name."""
    lowered = name.lower()
    caps: list[str] = []
    if any(hint in lowered for hint in EMBED_HINTS):
        return ["embedding"]
    if any(hint in lowered for hint in VISION_HINTS):
        caps.append("vision")
    if any(hint in lowered for hint in CODE_HINTS):
        caps.append("code")
    if any(hint in lowered for hint in REASONING_HINTS):
        caps.append("reasoning")
    if not caps:
        caps.append("general")
    # Anything that is not an embedding model can hold a conversation.
    if "chat" not in caps:
        caps.append("chat")
    return caps


class ModelRegistry:
    """Lists installed models, with a short TTL cache to avoid hammering the daemon."""

    def __init__(self):
        self._cache: list[ModelInfo] = []
        self._cached_at: float = 0.0
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def invalidate(self):
        self._cached_at = 0.0

    def list_models(self, force: bool = False) -> list[ModelInfo]:
        now = time.time()
        if not force and self._cache and (now - self._cached_at) < CACHE_TTL_SECONDS:
            return self._cache

        if settings.API_PROVIDER == "ollama":
            models = self._list_ollama()
        else:
            models = self._list_gateway()

        if models:
            self._cache = models
            self._cached_at = now
        return models

    # ------------------------------------------------------------------ #
    def _list_ollama(self) -> list[ModelInfo]:
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        payload = self._get_json(url)
        if payload is None:
            return []

        models: list[ModelInfo] = []
        for entry in payload.get("models", []):
            name = entry.get("name") or entry.get("model") or ""
            if not name:
                continue
            details = entry.get("details") or {}
            models.append(
                ModelInfo(
                    name=name,
                    size_bytes=int(entry.get("size") or 0),
                    family=str(details.get("family") or ""),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization=str(details.get("quantization_level") or ""),
                    capabilities=classify(name),
                )
            )
        models.sort(key=lambda m: m.name)
        return models

    def _list_gateway(self) -> list[ModelInfo]:
        base = (settings.GATEWAY_API_URL or "").rstrip("/")
        if not base:
            # Nothing to enumerate; surface the configured names so the UI is not empty.
            return [
                ModelInfo(name=settings.MODEL_NAME, capabilities=classify(settings.MODEL_NAME)),
                ModelInfo(name=settings.WORKER_MODEL_NAME, capabilities=classify(settings.WORKER_MODEL_NAME)),
            ]

        headers = {"Authorization": f"Bearer {settings.GATEWAY_API_KEY}"} if settings.GATEWAY_API_KEY else None
        payload = self._get_json(f"{base}/models", headers=headers)
        if payload is None:
            return []

        models = []
        for entry in payload.get("data", []):
            name = entry.get("id") or ""
            if name:
                models.append(ModelInfo(name=name, capabilities=classify(name)))
        models.sort(key=lambda m: m.name)
        return models

    def _get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        """Small dependency-free GET. Returns None and records the error on failure."""
        import json
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - fixed local/base URL
                self._last_error = None
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            self._last_error = f"Could not reach model host at {url}: {exc.reason}"
        except Exception as exc:
            self._last_error = f"Unexpected error listing models: {exc}"
        logger.warning("Model discovery failed", url=url, error=self._last_error)
        return None

    # ------------------------------------------------------------------ #
    def suggest(self) -> dict[str, str | None]:
        """Picks a reasonable default per role from what is installed."""
        models = self.list_models()
        names = [m.name for m in models]

        def first_with(capability: str) -> str | None:
            for model in models:
                if capability in model.capabilities:
                    return model.name
            return None

        return {
            "manager": settings.MODEL_NAME if settings.MODEL_NAME in names else first_with("reasoning"),
            "worker": settings.WORKER_MODEL_NAME if settings.WORKER_MODEL_NAME in names else first_with("code"),
            "vision": settings.VISION_MODEL_NAME if settings.VISION_MODEL_NAME in names else first_with("vision"),
        }

    def is_installed(self, name: str) -> bool:
        """Whether ``name`` is present. Tag-insensitive: ``llama3`` matches ``llama3:latest``."""
        if not name:
            return False
        installed = {m.name for m in self.list_models()}
        if name in installed:
            return True
        return any(existing.split(":")[0] == name.split(":")[0] for existing in installed)


model_registry = ModelRegistry()

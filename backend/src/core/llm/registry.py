"""Discovery of models the user can actually pick.

"Local first, user chooses their model" only works if the UI can find out what
is installed. Each provider is asked in its own dialect:

* **Ollama** -- ``/api/tags``, which reports size, family and quantization.
* **LM Studio** -- ``/api/v0/models`` (its native API) in preference to the
  OpenAI-compatible ``/v1/models``. The native route reports the real model
  ``type``, architecture, quantization, context length and *load state*; the
  compatible route returns bare ids. Falls back to ``/v1/models`` when the
  native route is absent, which is what a non-LM-Studio server on that URL
  would give.
* **Gateways** -- ``/v1/models``.

Capabilities are taken from provider metadata where it exists and guessed from
the model name only where it does not, so the frontend can suggest a sensible
default per role instead of showing one undifferentiated list.

Results are cached per provider: a session running its manager on one backend
and its worker on another must not have one list evict the other.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from src.config import LOCAL_PROVIDERS, PROVIDERS, settings
from src.utils.logging import logger


CACHE_TTL_SECONDS = 30

# An empty result is cached too, for a shorter window. Without this a provider
# that is merely switched off is re-probed on every lookup, and a refused TCP
# connect is not free -- Windows takes ~2s to report one. A single page load asks
# for the list and for a suggestion, so an offline provider cost four connects.
# The refresh control passes force=True, so "I just started it" is still instant.
FAILURE_TTL_SECONDS = 5

# Substrings that indicate a model is specialised. Ordered by specificity.
CODE_HINTS = ("coder", "code", "starcoder", "deepseek-coder", "codellama", "codegemma", "qwen2.5-coder")
REASONING_HINTS = ("r1", "reason", "think", "qwq", "o1", "phi-4", "marco")
VISION_HINTS = ("llava", "vision", "bakllava", "moondream", "minicpm-v", "gemma3", "pixtral")
EMBED_HINTS = ("embed", "bge", "minilm", "nomic", "mxbai", "gte")


# LM Studio reports a model `type` directly, which beats guessing from the name.
LMSTUDIO_TYPE_CAPABILITIES: dict[str, list[str]] = {
    "llm": ["general", "chat"],
    "vlm": ["vision", "chat"],
    "embeddings": ["embedding"],
}


@dataclass
class ModelInfo:
    name: str
    size_bytes: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    capabilities: list[str] = field(default_factory=list)
    installed: bool = True
    provider: str = ""
    context_length: int = 0
    # LM Studio loads a model on first use. That JIT load is tens of seconds on
    # a laptop, so the UI needs to be able to warn before the user commits.
    loaded: bool | None = None

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
    """Lists installed models per provider, with a short TTL cache per provider."""

    def __init__(self):
        self._cache: dict[str, list[ModelInfo]] = {}
        self._cached_at: dict[str, float] = {}
        self._errors: dict[str, str | None] = {}

    @property
    def last_error(self) -> str | None:
        """Error for the default provider, kept for callers that predate multi-provider."""
        return self.error_for(settings.API_PROVIDER)

    def error_for(self, provider: str | None = None) -> str | None:
        return self._errors.get(settings.resolve_provider(provider))

    def invalidate(self, provider: str | None = None):
        if provider is None:
            self._cached_at.clear()
        else:
            self._cached_at.pop(settings.resolve_provider(provider), None)

    def list_models(self, force: bool = False, provider: str | None = None) -> list[ModelInfo]:
        name = settings.resolve_provider(provider)
        now = time.time()
        cached = self._cache.get(name)
        if not force and cached is not None:
            ttl = CACHE_TTL_SECONDS if cached else FAILURE_TTL_SECONDS
            if (now - self._cached_at.get(name, 0.0)) < ttl:
                return cached

        if name == "ollama":
            models = self._list_ollama(name)
        elif name == "lmstudio":
            models = self._list_lmstudio(name)
        else:
            models = self._list_gateway(name)

        self._cache[name] = models
        self._cached_at[name] = now
        return models

    def available_providers(self) -> list[dict[str, Any]]:
        """Describes every provider the picker can offer, without probing any of them.

        Deliberately does no network I/O: this is rendered on every page load,
        and a provider that is merely configured-but-offline must not add its
        connect timeout to that.
        """
        return [
            {
                "id": name,
                "base_url": settings.provider_root_url(name),
                "configured": settings.provider_is_configured(name),
                "local": name in LOCAL_PROVIDERS,
                "is_default": name == settings.API_PROVIDER,
            }
            for name in PROVIDERS
        ]

    # ------------------------------------------------------------------ #
    def _list_ollama(self, provider: str) -> list[ModelInfo]:
        url = f"{settings.provider_root_url(provider)}/api/tags"
        payload = self._get_json(provider, url)
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
                    provider=provider,
                )
            )
        models.sort(key=lambda m: m.name)
        return models

    def _list_lmstudio(self, provider: str) -> list[ModelInfo]:
        root = settings.provider_root_url(provider)
        payload = self._get_json(provider, f"{root}/api/v0/models")
        if payload is None:
            # Either LM Studio is down or something else is serving that port.
            # The OpenAI-compatible route is the wider bet, so try it before
            # reporting failure -- and keep the native error if it fails too.
            native_error = self._errors.get(provider)
            fallback = self._list_gateway(provider, base_url=f"{root}/v1")
            if not fallback:
                self._errors[provider] = native_error
            return fallback

        models: list[ModelInfo] = []
        for entry in payload.get("data", []):
            name = entry.get("id") or ""
            if not name:
                continue
            model_type = str(entry.get("type") or "llm").lower()
            capabilities = list(LMSTUDIO_TYPE_CAPABILITIES.get(model_type, []))
            if not capabilities:
                capabilities = classify(name)
            elif model_type != "embeddings":
                # Merge in name-derived hints so a reasoning or coding model is
                # still tagged; LM Studio's `type` only distinguishes modality.
                for hint in classify(name):
                    if hint in {"code", "reasoning"} and hint not in capabilities:
                        capabilities.append(hint)

            models.append(
                ModelInfo(
                    name=name,
                    family=str(entry.get("arch") or ""),
                    quantization=str(entry.get("quantization") or ""),
                    capabilities=capabilities,
                    provider=provider,
                    context_length=int(entry.get("max_context_length") or 0),
                    loaded=str(entry.get("state") or "") == "loaded",
                )
            )
        models.sort(key=lambda m: m.name)
        return models

    def _list_gateway(self, provider: str, base_url: str | None = None) -> list[ModelInfo]:
        base = (base_url if base_url is not None else settings.provider_openai_base_url(provider)).rstrip("/")
        if not base:
            # Nothing to enumerate; surface the configured names so the UI is not empty.
            return [
                ModelInfo(name=settings.MODEL_NAME, capabilities=classify(settings.MODEL_NAME), provider=provider),
                ModelInfo(
                    name=settings.WORKER_MODEL_NAME,
                    capabilities=classify(settings.WORKER_MODEL_NAME),
                    provider=provider,
                ),
            ]

        api_key = settings.provider_api_key(provider)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        payload = self._get_json(provider, f"{base}/models", headers=headers)
        if payload is None:
            return []

        models = []
        for entry in payload.get("data", []):
            name = entry.get("id") or ""
            if name:
                models.append(ModelInfo(name=name, capabilities=classify(name), provider=provider))
        models.sort(key=lambda m: m.name)
        return models

    def _get_json(self, provider: str, url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        """Small dependency-free GET. Returns None and records the error on failure."""
        import json
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - fixed local/base URL
                self._errors[provider] = None
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            self._errors[provider] = f"Could not reach {provider} at {url}: {exc.reason}"
        except Exception as exc:
            self._errors[provider] = f"Unexpected error listing {provider} models: {exc}"
        logger.warning("Model discovery failed", provider=provider, url=url, error=self._errors[provider])
        return None

    # ------------------------------------------------------------------ #
    def suggest(self, provider: str | None = None) -> dict[str, str | None]:
        """Picks a reasonable default per role from what is installed."""
        name = settings.resolve_provider(provider)
        models = self.list_models(provider=name)
        names = [m.name for m in models]

        def first_with(capability: str) -> str | None:
            for model in models:
                if capability in model.capabilities:
                    return model.name
            return None

        def pick(configured: str, capability: str) -> str | None:
            # The configured default is only meaningful on the provider that
            # holds it: "deepseek-r1:1.5b" is an Ollama tag and will 404 on a
            # gateway, so on any other provider fall straight through to what
            # is actually there.
            if configured in names:
                return configured
            return first_with(capability) or (names[0] if names else None)

        return {
            "manager": pick(settings.MODEL_NAME, "reasoning"),
            "worker": pick(settings.WORKER_MODEL_NAME, "code"),
            "vision": settings.VISION_MODEL_NAME if settings.VISION_MODEL_NAME in names else first_with("vision"),
        }

    def is_installed(self, name: str, provider: str | None = None) -> bool:
        """Whether ``name`` is present. Tag-insensitive: ``llama3`` matches ``llama3:latest``."""
        if not name:
            return False
        installed = {m.name for m in self.list_models(provider=provider)}
        if name in installed:
            return True
        return any(existing.split(":")[0] == name.split(":")[0] for existing in installed)


model_registry = ModelRegistry()

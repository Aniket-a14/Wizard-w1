"""Provider-agnostic LLM access with first-class token streaming.

Two things this replaces:

1. ``DataAnalysisAgent._get_llm`` / ``_get_worker_llm``, which cached exactly one
   manager and one worker client on the agent instance. That made per-request
   model selection impossible -- the first model chosen was the only model the
   process would ever use.
2. Blocking ``llm.invoke()`` calls. Every entry point here has a streaming twin
   so the UI can render tokens as they are produced instead of faking a reveal
   animation over an already-complete string.

Clients are cached by a (provider, endpoint, model, temperature, ...) key so
switching models is cheap and switching back reuses the warm client.

The provider is part of that key, and part of every call signature, because it
is a per-request choice rather than process-wide configuration: one analysis can
plan on an Ollama reasoning model and generate code on an LM Studio one.
``settings.API_PROVIDER`` is only the default used when a caller names none.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.config import settings
from src.core.llm.resources import ResidentPlan, plan_for_models
from src.utils.logging import logger


class LLMRole(StrEnum):
    """Which brain is being addressed. Determines the default model."""

    MANAGER = "manager"  # planning, critique, replanning
    WORKER = "worker"  # code generation
    VISION = "vision"  # plot description


@dataclass(frozen=True)
class ModelSpec:
    """A fully-resolved request for a specific model on a specific backend.

    The endpoint is captured here rather than read from ``settings`` inside
    ``_build_client``, because a single request can involve two providers -- a
    manager on Ollama and a worker on LM Studio, say -- and the cache key has to
    tell those apart.
    """

    provider: str
    model: str
    temperature: float
    max_tokens: int
    num_ctx: int
    base_url: str = ""
    api_key: str = ""
    #: How long the server should hold this model after the call. Derived from
    #: whether the manager and worker can share memory on this machine, so it is
    #: part of the cache key -- a client built when they fitted must not be
    #: reused once they do not.
    keep_alive: str = ""

    def cache_key(self) -> tuple:
        return (
            self.provider,
            self.base_url,
            self.model,
            self.temperature,
            self.max_tokens,
            self.num_ctx,
            self.keep_alive,
        )


class LLMUnavailableError(RuntimeError):
    """Raised when no client could be constructed for a request."""


class LLMProvider:
    """Builds, caches and drives chat clients across Ollama and OpenAI-compatible gateways."""

    def __init__(self):
        self._clients: dict[tuple, Any] = {}
        self._plans: dict[tuple, ResidentPlan] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Resolution
    # ------------------------------------------------------------------ #
    def default_model_for(self, role: LLMRole, provider: str | None = None) -> str:
        """The model to use when the caller names none.

        A configured ``*_MODEL_NAME`` is an explicit pin and always wins. When it
        is empty -- the default -- the model is discovered from what the provider
        actually has installed, so the app runs against any model on any backend
        instead of failing on two hardcoded Ollama tags that do not exist
        anywhere else.
        """
        pinned = {
            LLMRole.WORKER: settings.WORKER_MODEL_NAME,
            LLMRole.VISION: settings.VISION_MODEL_NAME,
            LLMRole.MANAGER: settings.MODEL_NAME,
        }.get(role, settings.MODEL_NAME)
        if pinned.strip():
            return pinned.strip()

        # Imported lazily: `llm/__init__` loads this module before `registry`,
        # and discovery must not run as an import side effect.
        from src.core.llm.registry import model_registry

        try:
            return (model_registry.suggest(provider).get(role.value) or "").strip()
        except Exception as exc:  # pragma: no cover - discovery is best effort
            logger.warning("Model discovery failed while resolving a default", role=role.value, error=str(exc))
            return ""

    def resolve(
        self,
        role: LLMRole,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: str | None = None,
    ) -> ModelSpec:
        """Turns a role plus optional per-request overrides into a concrete spec."""
        resolved_provider = settings.resolve_provider(provider)
        return ModelSpec(
            provider=resolved_provider,
            model=(model or self.default_model_for(role, resolved_provider)).strip(),
            temperature=settings.TEMPERATURE if temperature is None else float(temperature),
            max_tokens=max_tokens or settings.MAX_TOKENS,
            num_ctx=settings.LLM_NUM_CTX,
            keep_alive=self.keep_alive_for(resolved_provider),
            base_url=settings.provider_openai_base_url(resolved_provider)
            if resolved_provider != "ollama"
            else settings.provider_root_url(resolved_provider),
            api_key=settings.provider_api_key(resolved_provider),
        )

    def resident_plan(self, provider: str | None = None) -> ResidentPlan:
        """Whether the manager and worker can be resident on this machine at once.

        Planned for the *pair*, not the role being resolved: the cost being
        avoided is one evicting the other, which is a property of both.
        """
        resolved = settings.resolve_provider(provider)
        manager = self.default_model_for(LLMRole.MANAGER, resolved)
        worker = self.default_model_for(LLMRole.WORKER, resolved)
        key = (resolved, manager, worker, settings.LLM_NUM_CTX)
        cached = self._plans.get(key)
        if cached is None:
            cached = plan_for_models([manager, worker], resolved, settings.LLM_NUM_CTX)
            self._plans[key] = cached
            if not cached.co_resident:
                logger.info(
                    "Models will be swapped rather than co-resident",
                    reason=cached.reason,
                    keep_alive=cached.keep_alive,
                )
        return cached

    def keep_alive_for(self, provider: str) -> str:
        """How long this provider should hold a model after a call.

        Only Ollama takes a keep-alive. LM Studio manages residency itself and
        the gateways host the model elsewhere, so there is nothing to say.
        """
        if provider != "ollama":
            return ""
        try:
            return self.resident_plan(provider).keep_alive
        except Exception as exc:  # pragma: no cover - planning must never block a call
            logger.warning("Memory planning failed; using the default keep-alive", error=str(exc))
            return settings.LLM_KEEP_ALIVE

    # ------------------------------------------------------------------ #
    # Client construction
    # ------------------------------------------------------------------ #
    def get_client(self, spec: ModelSpec):
        key = spec.cache_key()
        client = self._clients.get(key)
        if client is not None:
            return client

        with self._lock:
            client = self._clients.get(key)
            if client is not None:
                return client
            client = self._build_client(spec)
            if client is not None:
                self._clients[key] = client
            return client

    def _build_client(self, spec: ModelSpec):
        if not spec.model:
            # Reached when no model is pinned and discovery found nothing, i.e.
            # the daemon is down or has no models pulled. Constructing a client
            # for the empty string would fail later with a far worse message.
            logger.warning("No model resolved", provider=spec.provider, base_url=spec.base_url)
            return None
        try:
            if spec.provider == "ollama":
                from langchain_ollama import ChatOllama

                logger.info("Initializing ChatOllama client", model=spec.model, temperature=spec.temperature)
                return ChatOllama(
                    model=spec.model,
                    base_url=spec.base_url or settings.OLLAMA_BASE_URL,
                    temperature=spec.temperature,
                    num_predict=spec.max_tokens,
                    num_ctx=spec.num_ctx,
                    num_thread=settings.LLM_NUM_THREAD,
                    repeat_penalty=1.1,
                    # The manager and worker alternate every iteration, so an
                    # eviction between them costs a full reload from disk each
                    # time. Ollama's own default is five minutes, which one slow
                    # turn can exceed while it is still running.
                    # Long when the manager and worker fit in memory together,
                    # short when they do not -- see `core/llm/resources.py`.
                    keep_alive=spec.keep_alive or settings.LLM_KEEP_ALIVE,
                    # ChatOllama has no `timeout` field, so this is the only way
                    # to bound a request. Without it a wedged daemon hangs the
                    # turn forever -- the OpenAI-compatible path has had a
                    # timeout all along and this one had none.
                    client_kwargs={"timeout": settings.LLM_REQUEST_TIMEOUT},
                )

            try:
                from langchain_openai import ChatOpenAI
            except ImportError:  # pragma: no cover - depends on optional extra
                from langchain_community.chat_models import ChatOpenAI

            # LM Studio, vLLM, llama.cpp's server and hosted gateways all speak
            # this dialect. Note that context length is *not* sent: LM Studio
            # fixes it when the model is loaded, so LLM_NUM_CTX has no effect here.
            logger.info(
                "Initializing OpenAI-compatible client",
                provider=spec.provider,
                model=spec.model,
                base_url=spec.base_url or "<default>",
            )
            return ChatOpenAI(
                model=spec.model,
                base_url=spec.base_url or None,
                api_key=spec.api_key or "not-required",
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                timeout=settings.LLM_REQUEST_TIMEOUT,
            )
        except Exception as exc:
            logger.error("Failed to construct LLM client", provider=spec.provider, model=spec.model, error=str(exc))
            return None

    def clear_cache(self):
        """Drops cached clients so new settings (base URL, temperature) take effect."""
        with self._lock:
            self._clients.clear()

    # ------------------------------------------------------------------ #
    # Invocation
    # ------------------------------------------------------------------ #
    def complete(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Blocking completion. Returns "" when the provider is unreachable."""
        spec = self.resolve(role, model=model, temperature=temperature, provider=provider, max_tokens=max_tokens)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(self._unavailable_message(spec))
        try:
            response = client.invoke(prompt)
            return self._extract_text(response)
        except Exception as exc:
            logger.error("LLM completion failed", provider=spec.provider, model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def acomplete(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        spec = self.resolve(role, model=model, temperature=temperature, provider=provider, max_tokens=max_tokens)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(self._unavailable_message(spec))
        try:
            response = await client.ainvoke(prompt)
            return self._extract_text(response)
        except Exception as exc:
            logger.error("LLM completion failed", provider=spec.provider, model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def astream(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yields text deltas as the model produces them.

        Falls back to a single yield of the full response when the underlying
        client does not implement ``astream``.
        """
        spec = self.resolve(role, model=model, temperature=temperature, provider=provider, max_tokens=max_tokens)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(self._unavailable_message(spec))

        if not hasattr(client, "astream"):
            yield await self.acomplete(
                prompt,
                role=role,
                model=model,
                temperature=temperature,
                provider=provider,
                max_tokens=max_tokens,
            )
            return

        try:
            async for chunk in client.astream(prompt):
                text = self._extract_text(chunk)
                if text:
                    yield text
        except Exception as exc:
            logger.error("LLM streaming failed", provider=spec.provider, model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def stream_to(
        self,
        prompt: str,
        on_delta: Callable[[str], Any] | None = None,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Streams a completion, invoking ``on_delta`` per chunk, and returns the full text.

        ``on_delta`` may be sync or async; both are supported so callers can push
        straight into a WebSocket without wrapping.
        """
        buffer: list[str] = []
        async for delta in self.astream(
            prompt,
            role=role,
            model=model,
            temperature=temperature,
            provider=provider,
            max_tokens=max_tokens,
        ):
            buffer.append(delta)
            if on_delta is not None:
                result = on_delta(delta)
                if asyncio.iscoroutine(result):
                    await result
        return "".join(buffer)

    async def describe_image(self, base64_png: str, model: str | None = None, provider: str | None = None) -> str:
        """Multimodal description of a rendered chart."""
        spec = self.resolve(LLMRole.VISION, model=model, temperature=0.2, provider=provider)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(self._unavailable_message(spec))

        from langchain_core.messages import HumanMessage

        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Describe this data visualization in 2-3 sentences. "
                        "Explain the visible trend, the axes, and any key insight."
                    ),
                },
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_png}"}},
            ]
        )
        response = await client.ainvoke([message])
        return self._extract_text(response).strip()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _unavailable_message(spec: ModelSpec) -> str:
        """Names the endpoint, since 'no client available' alone is undebuggable.

        The usual cause is a local daemon that is not running, and the user can
        only check that if they are told which host was tried.
        """
        where = spec.base_url or "the configured endpoint"
        if not spec.model:
            return (
                f"No model is available on {spec.provider} at {where}. "
                "Nothing is pinned in the configuration and discovery found none installed."
            )
        return f"No LLM client available for '{spec.model}' on {spec.provider} at {where}"

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Normalises the several shapes LangChain returns into plain text."""
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        content = getattr(response, "content", None)
        if content is None:
            return str(response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "".join(parts)
        return str(content)


llm_provider = LLMProvider()

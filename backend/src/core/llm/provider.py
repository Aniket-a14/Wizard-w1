"""Provider-agnostic LLM access with first-class token streaming.

Two things this replaces:

1. ``DataAnalysisAgent._get_llm`` / ``_get_worker_llm``, which cached exactly one
   manager and one worker client on the agent instance. That made per-request
   model selection impossible -- the first model chosen was the only model the
   process would ever use.
2. Blocking ``llm.invoke()`` calls. Every entry point here has a streaming twin
   so the UI can render tokens as they are produced instead of faking a reveal
   animation over an already-complete string.

Clients are cached by a (provider, model, temperature, ...) key so switching
models is cheap and switching back reuses the warm client.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.config import settings
from src.utils.logging import logger


class LLMRole(StrEnum):
    """Which brain is being addressed. Determines the default model."""

    MANAGER = "manager"  # planning, critique, replanning
    WORKER = "worker"  # code generation
    VISION = "vision"  # plot description


@dataclass(frozen=True)
class ModelSpec:
    """A fully-resolved request for a specific model."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    num_ctx: int

    def cache_key(self) -> tuple:
        return (self.provider, self.model, self.temperature, self.max_tokens, self.num_ctx)


class LLMUnavailableError(RuntimeError):
    """Raised when no client could be constructed for a request."""


class LLMProvider:
    """Builds, caches and drives chat clients across Ollama and OpenAI-compatible gateways."""

    def __init__(self):
        self._clients: dict[tuple, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Resolution
    # ------------------------------------------------------------------ #
    def default_model_for(self, role: LLMRole) -> str:
        if role is LLMRole.WORKER:
            return settings.WORKER_MODEL_NAME
        if role is LLMRole.VISION:
            return settings.VISION_MODEL_NAME
        return settings.MODEL_NAME

    def resolve(
        self,
        role: LLMRole,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelSpec:
        """Turns a role plus optional per-request overrides into a concrete spec."""
        return ModelSpec(
            provider=settings.API_PROVIDER,
            model=(model or self.default_model_for(role)).strip(),
            temperature=settings.TEMPERATURE if temperature is None else float(temperature),
            max_tokens=max_tokens or settings.MAX_TOKENS,
            num_ctx=settings.LLM_NUM_CTX,
        )

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
        try:
            if spec.provider == "ollama":
                from langchain_ollama import ChatOllama

                logger.info("Initializing ChatOllama client", model=spec.model, temperature=spec.temperature)
                return ChatOllama(
                    model=spec.model,
                    base_url=settings.OLLAMA_BASE_URL,
                    temperature=spec.temperature,
                    num_predict=spec.max_tokens,
                    num_ctx=spec.num_ctx,
                    num_thread=settings.LLM_NUM_THREAD,
                    repeat_penalty=1.1,
                )

            try:
                from langchain_openai import ChatOpenAI
            except ImportError:  # pragma: no cover - depends on optional extra
                from langchain_community.chat_models import ChatOpenAI

            logger.info("Initializing OpenAI-compatible gateway client", model=spec.model)
            return ChatOpenAI(
                model=spec.model,
                base_url=settings.GATEWAY_API_URL or None,
                api_key=settings.GATEWAY_API_KEY or "not-required",
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                timeout=settings.LLM_REQUEST_TIMEOUT,
            )
        except Exception as exc:
            logger.error("Failed to construct LLM client", model=spec.model, error=str(exc))
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
    ) -> str:
        """Blocking completion. Returns "" when the provider is unreachable."""
        spec = self.resolve(role, model=model, temperature=temperature)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(f"No LLM client available for model '{spec.model}'")
        try:
            response = client.invoke(prompt)
            return self._extract_text(response)
        except Exception as exc:
            logger.error("LLM completion failed", model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def acomplete(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        spec = self.resolve(role, model=model, temperature=temperature)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(f"No LLM client available for model '{spec.model}'")
        try:
            response = await client.ainvoke(prompt)
            return self._extract_text(response)
        except Exception as exc:
            logger.error("LLM completion failed", model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def astream(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yields text deltas as the model produces them.

        Falls back to a single yield of the full response when the underlying
        client does not implement ``astream``.
        """
        spec = self.resolve(role, model=model, temperature=temperature)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError(f"No LLM client available for model '{spec.model}'")

        if not hasattr(client, "astream"):
            yield await self.acomplete(prompt, role=role, model=model, temperature=temperature)
            return

        try:
            async for chunk in client.astream(prompt):
                text = self._extract_text(chunk)
                if text:
                    yield text
        except Exception as exc:
            logger.error("LLM streaming failed", model=spec.model, error=str(exc))
            raise LLMUnavailableError(str(exc)) from exc

    async def stream_to(
        self,
        prompt: str,
        on_delta: Callable[[str], Any] | None = None,
        role: LLMRole = LLMRole.MANAGER,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Streams a completion, invoking ``on_delta`` per chunk, and returns the full text.

        ``on_delta`` may be sync or async; both are supported so callers can push
        straight into a WebSocket without wrapping.
        """
        buffer: list[str] = []
        async for delta in self.astream(prompt, role=role, model=model, temperature=temperature):
            buffer.append(delta)
            if on_delta is not None:
                result = on_delta(delta)
                if asyncio.iscoroutine(result):
                    await result
        return "".join(buffer)

    async def describe_image(self, base64_png: str, model: str | None = None) -> str:
        """Multimodal description of a rendered chart."""
        spec = self.resolve(LLMRole.VISION, model=model, temperature=0.2)
        client = self.get_client(spec)
        if client is None:
            raise LLMUnavailableError("Vision model unavailable")

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

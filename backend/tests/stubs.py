"""Scripted stand-ins for the LLM provider.

Importable from any test module: ``backend/tests`` is on ``sys.path`` because
``conftest.py`` lives there. Kept out of ``conftest.py`` itself so the classes
can be subclassed without importing the conftest module by name.

Every test in the suite runs against these. Nothing here contacts a model
server, which is what lets the whole suite run offline and in CI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator


class ScriptedLLM:
    """Returns queued responses in order and records every prompt it received.

    Running out of responses yields ``"Done."`` rather than raising: a test
    should fail on its own assertion about behaviour, not on an IndexError from
    the stub, which says nothing about what went wrong.
    """

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def _next(self) -> str:
        self.prompts.append("")
        return self.responses.pop(0) if self.responses else "No more scripted responses."

    async def acomplete(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else "Done."

    def complete(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else "Done."

    async def astream(self, prompt: str, **_: object) -> AsyncIterator[str]:
        text = await self.acomplete(prompt)
        # Emit in small pieces so streaming behaviour is genuinely exercised.
        for index in range(0, len(text), 7):
            yield text[index : index + 7]

    async def stream_to(self, prompt: str, on_delta=None, **_: object) -> str:
        chunks: list[str] = []
        async for delta in self.astream(prompt):
            chunks.append(delta)
            if on_delta is not None:
                result = on_delta(delta)
                if hasattr(result, "__await__"):
                    await result
        return "".join(chunks)


class RecordingLLM(ScriptedLLM):
    """Scripted, but also records which (role, model, provider) each call used."""

    def __init__(self, responses: list[str]):
        super().__init__(responses)
        self.calls: list[dict] = []

    def _record(self, kwargs: dict) -> None:
        self.calls.append(
            {
                "role": str(kwargs.get("role", "")),
                "model": kwargs.get("model"),
                "provider": kwargs.get("provider"),
            }
        )

    async def acomplete(self, prompt: str, **kwargs: object) -> str:
        self._record(kwargs)
        return await super().acomplete(prompt)

    def complete(self, prompt: str, **kwargs: object) -> str:
        self._record(kwargs)
        return super().complete(prompt)

    async def stream_to(self, prompt: str, on_delta=None, **kwargs: object) -> str:
        self._record(kwargs)
        return await super().stream_to(prompt, on_delta)

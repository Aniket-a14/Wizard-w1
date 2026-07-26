"""Event protocol between the orchestrator and any transport.

The orchestrator does not know about WebSockets. It emits typed events; the
transport decides how to serialise them. That is what lets the same run drive a
streaming socket, a buffered REST response and a test collector without the
duplicated node-sequencing loop the previous WebSocket handler carried.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    SESSION = "session"
    STATUS = "status"
    STEP_START = "step_start"
    STEP_END = "step_end"
    REASONING_DELTA = "reasoning_delta"
    PLAN_DELTA = "plan_delta"
    CONTENT_DELTA = "content_delta"
    CODE = "code"
    STDOUT = "stdout"
    ARTIFACT = "artifact"
    APPROVAL_REQUIRED = "approval_required"
    WARNING = "warning"
    ERROR = "error"
    FINAL = "final"


class Phase(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    SEARCHING = "searching"
    GENERATING = "generating"
    EXECUTING = "executing"
    CORRECTING = "correcting"
    REVIEWING = "reviewing"
    ANSWERING = "answering"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "at": self.at, **self.data}


# An emitter may be sync or async; ``emit`` normalises both.
Emitter = Callable[[Event], Awaitable[None] | None]


async def emit(emitter: Emitter | None, event_type: EventType, **data: Any) -> None:
    """Sends one event, tolerating a missing or synchronous emitter."""
    if emitter is None:
        return
    import asyncio

    result = emitter(Event(type=event_type, data=data))
    if asyncio.iscoroutine(result):
        await result


class EventCollector:
    """Buffers events. Used by the REST path and by tests."""

    def __init__(self):
        self.events: list[Event] = []

    def __call__(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [event for event in self.events if event.type is event_type]

    def text_of(self, event_type: EventType) -> str:
        return "".join(str(event.data.get("content", "")) for event in self.of_type(event_type))

    def as_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]

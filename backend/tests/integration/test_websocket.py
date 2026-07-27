"""Integration tests for the streaming WebSocket transport."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Iterator

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.core.session import session_manager


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


@pytest.fixture
def session_with_data(client: TestClient, simple_df: pd.DataFrame) -> str:
    buffer = io.StringIO()
    simple_df.to_csv(buffer, index=False)
    response = client.post(
        "/api/datasets?clean=false",
        files={"file": ("data.csv", buffer.getvalue().encode(), "text/csv")},
    )
    return response.json()["session_id"]


class StreamingStub:
    """Scripted LLM that emits its response in several chunks."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    async def acomplete(self, prompt: str, **_: object) -> str:
        return self.responses.pop(0) if self.responses else "Done."

    def complete(self, prompt: str, **_: object) -> str:
        return self.responses.pop(0) if self.responses else "Done."

    async def astream(self, prompt: str, **_: object) -> AsyncIterator[str]:
        text = await self.acomplete(prompt)
        for index in range(0, len(text), 5):
            yield text[index : index + 5]

    async def stream_to(self, prompt: str, on_delta=None, **_: object) -> str:
        chunks: list[str] = []
        async for delta in self.astream(prompt):
            chunks.append(delta)
            if on_delta is not None:
                result = on_delta(delta)
                if hasattr(result, "__await__"):
                    await result
        return "".join(chunks)


def collect_until(websocket, terminal: set[str], limit: int = 200) -> list[dict]:
    """Drains frames until a terminal type arrives."""
    frames: list[dict] = []
    for _ in range(limit):
        frame = websocket.receive_json()
        frames.append(frame)
        if frame.get("type") in terminal:
            break
    return frames


def test_socket_announces_the_session(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as websocket:
        frame = websocket.receive_json()
        assert frame["type"] == "session"
        assert frame["session_id"]


def test_ping_is_answered(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()  # session frame
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json()["type"] == "pong"


def test_message_without_a_dataset_is_rejected(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "message", "content": "analyse this", "mode": "fast"})

        frame = websocket.receive_json()
        assert frame["type"] == "error"
        assert "dataset" in frame["content"].lower()


def test_blank_message_is_ignored(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "message", "content": "   "})
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json()["type"] == "pong"


def test_full_run_streams_tokens_then_finishes(client: TestClient, session_with_data: str, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.core.agent.orchestrator.llm_provider",
        StreamingStub(
            [
                "1. Print the row count",
                "```python\nprint(len(df))\n```",
                "The dataset has five rows in total.",
            ]
        ),
    )

    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()  # session frame
        websocket.send_json({"type": "message", "content": "how many rows", "mode": "fast"})
        frames = collect_until(websocket, {"final", "error"})

    types = [frame["type"] for frame in frames]
    assert "final" in types, f"run never completed: {types}"
    assert types.count("content_delta") > 1, "the answer did not stream"
    assert "code" in types

    final = frames[-1]
    assert "five rows" in final["response"]


def test_planning_mode_emits_an_approval_request(client: TestClient, session_with_data: str, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.core.agent.orchestrator.llm_provider",
        StreamingStub(["<thought>Thinking it through.</thought>\n1. Load\n2. Summarise"]),
    )

    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "message", "content": "summarise", "mode": "planning"})
        frames = collect_until(websocket, {"approval_required", "error", "final"})

    approval = frames[-1]
    assert approval["type"] == "approval_required"
    assert approval["tool"] == "execute_plan"

    reasoning = "".join(f["content"] for f in frames if f["type"] == "reasoning_delta")
    assert "Thinking it through" in reasoning


def test_approval_resumes_the_run(client: TestClient, session_with_data: str, monkeypatch) -> None:
    """Approving a plan resumes it with the full investigation budget.

    The approved plan must not re-enter the approval gate, and must not be
    downgraded to a single-shot run: approving the work is not the same as
    asking for less of it.
    """
    monkeypatch.setattr(
        "src.core.agent.orchestrator.llm_provider",
        StreamingStub(
            [
                "```python\nprint('ok')\n```",  # iteration 1 writes the code
                "ACTION: answer\nGOAL: report it",  # iteration 2 decides it is done
                "```python\nprint('VERIFIED: ok')\n```",  # the verification pass
                "The step completed.",  # answer synthesis
            ]
        ),
    )

    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "approval",
                "approved": True,
                "tool": "execute_plan",
                "content": "summarise",
                "plan": "1. Print ok\n2. Stop",
            }
        )
        frames = collect_until(websocket, {"final", "error"})

    assert frames[-1]["type"] == "final"
    assert "completed" in frames[-1]["response"]
    # No second approval_required: the gate lives in orientation, which an
    # approved plan skips entirely.
    assert not [frame for frame in frames if frame["type"] == "approval_required"]


def test_rejected_approval_stops_cleanly(client: TestClient, session_with_data: str) -> None:
    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "approval", "approved": False, "tool": "execute_plan", "content": "summarise"})

        frame = websocket.receive_json()
        assert frame["type"] == "status"
        assert "reject" in frame["content"].lower()


def test_socket_survives_a_malformed_frame(client: TestClient, session_with_data: str) -> None:
    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "unknown_kind", "content": ""})
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json()["type"] == "pong"


def test_cancel_is_accepted_when_idle(client: TestClient, session_with_data: str) -> None:
    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "cancel"})

        frame = websocket.receive_json()
        assert frame["type"] == "status"
        assert frame["content"] == "Cancelled"


def test_socket_reuses_an_existing_session(client: TestClient, session_with_data: str) -> None:
    with client.websocket_connect(f"/ws/chat?session={session_with_data}") as websocket:
        frame = websocket.receive_json()
        assert frame["session_id"] == session_with_data

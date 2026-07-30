"""Chat: a buffered REST endpoint and a streaming WebSocket.

Both drive the same :class:`AnalysisOrchestrator`. The WebSocket handler used to
re-implement the node sequencing by hand, which is why the cache lookup and the
fast-path router silently applied to `POST /chat` only. Here the transport does
nothing but translate events into frames.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect

from src.api.deps import SESSION_HEADER, require_api_key, require_dataset, ws_gate
from src.api.schemas import ChatRequest, ChatResponse
from src.config import settings
from src.core.agent.events import Event, EventCollector, EventType
from src.core.agent.orchestrator import orchestrator
from src.core.session import Session, session_manager
from src.utils.logging import logger


router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat(
    request: ChatRequest,
    response: Response,
    session: Session = Depends(require_dataset),
) -> ChatResponse:
    """Runs a full turn and returns the finished answer.

    Use the WebSocket for token streaming; this exists for scripts and integrations.
    """
    session.append_message("user", request.message)
    collector = EventCollector()

    result = await orchestrator.run(
        session=session,
        instruction=request.message,
        mode=request.mode,
        emitter=collector,
        approved_plan=request.approved_plan,
    )

    response.headers[SESSION_HEADER] = session.id
    payload = result.to_dict()
    return ChatResponse(
        response=payload["response"],
        code=payload["code"],
        thought=payload["thought"],
        plan=payload["plan"],
        image=payload["image"],
        status=payload["status"],
        artifacts=payload["artifacts"],
        warnings=payload["warnings"],
        approval=payload["approval"],
        downloads=payload["downloads"],
        elapsed_ms=payload["elapsed_ms"],
        findings=payload["findings"],
        assumptions=payload["assumptions"],
        iterations=payload["iterations"],
        tier=payload["tier"],
        mode=payload["mode"],
        verification=payload["verification"],
        grounding=payload["grounding"],
    )


class WebSocketEmitter:
    """Serialises orchestrator events onto a socket.

    Send failures are swallowed: a client that navigated away must not surface as
    an orchestrator exception mid-run.
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.closed = False

    async def __call__(self, event: Event) -> None:
        if self.closed:
            return
        try:
            await self.websocket.send_json(event.to_dict())
        except (WebSocketDisconnect, RuntimeError):
            self.closed = True
        except Exception as exc:
            self.closed = True
            logger.debug("Dropping event, socket unusable", error=str(exc))


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """Streaming chat.

    Client frames
    -------------
    ``{"type": "message", "content": str, "mode": "auto"|"fast"|"deep"|"planning"}``
    ``{"type": "approval", "approved": bool, "tool": str, "content": str, "plan"?: str, "query"?: str}``
    ``{"type": "cancel"}``  ``{"type": "ping"}``

    Server frames are the orchestrator's event types plus ``session`` and ``pong``.
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    if not ws_gate.acquire(client_host):
        await websocket.close(code=1013, reason="Too many concurrent connections.")
        return

    await websocket.accept()

    api_key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    if settings.API_KEY and api_key != settings.API_KEY:
        await websocket.send_json({"type": "error", "content": "Invalid or missing API key."})
        await websocket.close(code=1008)
        ws_gate.release(client_host)
        return

    session_id = websocket.query_params.get("session") or websocket.headers.get(SESSION_HEADER.lower())
    session = session_manager.get_or_create(session_id)

    emitter = WebSocketEmitter(websocket)
    current_run: asyncio.Task | None = None
    last_code: str | None = None

    await websocket.send_json({"type": EventType.SESSION.value, "session_id": session.id})

    async def resolve_session() -> Session:
        """Re-resolves the socket's session, and counts the frame as activity.

        Binding the object once at connect meant an eviction or a TTL reap left
        the socket holding a *disposed* ``Session``. ``dispose()`` clears
        ``datasets``, so the next question answered "No dataset is loaded" for
        data the user had just uploaded, against a runtime already released.
        Sessions are capped (``SESSION_MAX_ACTIVE``, which host sizing derives
        to 7 on a 16 GB laptop) and evicted least-recently-seen, so a few tabs
        or a backend restart reach this.
        """
        nonlocal session
        live = session_manager.get(session.id)  # get() touches on a hit
        if live is not None:
            return live
        session = session_manager.create()
        # The id changed underneath the client. Without telling it, its stored
        # id keeps naming the dead session and every later REST call -- upload
        # included -- lands somewhere this socket cannot see.
        await websocket.send_json({"type": EventType.SESSION.value, "session_id": session.id})
        return session

    try:
        while True:
            payload: dict[str, Any] = await websocket.receive_json()
            kind = payload.get("type", "message")

            # Every frame, before anything branches on it. A heartbeat is proof
            # the client is still there, so it has to count against eviction:
            # `ping` used to return before the session was touched, which left
            # a connected tab holding a dataset ageing to the top of the
            # least-recently-seen order while it sat idle.
            session = await resolve_session()

            if kind == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if kind == "cancel":
                if current_run and not current_run.done():
                    current_run.cancel()
                await asyncio.to_thread(session.executor.interrupt)
                await websocket.send_json({"type": EventType.STATUS.value, "content": "Cancelled", "phase": "idle"})
                continue

            if current_run and not current_run.done():
                await websocket.send_json(
                    {"type": EventType.ERROR.value, "content": "A run is already in progress on this session."}
                )
                continue

            # An empty frame is a no-op in every case, so it is discarded before
            # any state check: a blank message should not raise "no dataset".
            instruction = (payload.get("content") or "").strip()
            if not instruction:
                continue

            if not session.has_data:
                await websocket.send_json(
                    {
                        "type": EventType.ERROR.value,
                        "content": "No dataset is loaded. Upload a file before asking a question.",
                    }
                )
                continue

            mode = payload.get("mode", "auto")
            approved_plan: str | None = None
            approved_search: str | None = None

            if kind == "approval":
                if not payload.get("approved"):
                    await websocket.send_json(
                        {"type": EventType.STATUS.value, "content": "Plan rejected", "phase": "idle"}
                    )
                    continue
                tool = payload.get("tool")
                if tool == "web_search":
                    approved_search = payload.get("query") or ""
                else:
                    approved_plan = payload.get("plan") or instruction
                    # Already approved, so the gate must not fire again — but the
                    # investigation still gets its full budget. Downgrading to
                    # `fast` here would have made approving a plan silently
                    # reduce the work done to carry it out.
                    mode = "auto" if mode == "planning" else mode
            else:
                session.append_message("user", instruction)

            async def run_turn(
                instruction: str = instruction,
                mode: str = mode,
                approved_plan: str | None = approved_plan,
                approved_search: str | None = approved_search,
            ):
                nonlocal last_code
                result = await orchestrator.run(
                    session=session,
                    instruction=instruction,
                    mode=mode,
                    emitter=emitter,
                    approved_plan=approved_plan,
                    approved_search=approved_search,
                    previous_code=last_code,
                )
                if result.code:
                    last_code = result.code

            current_run = asyncio.ensure_future(run_turn())
            try:
                await current_run
            except asyncio.CancelledError:
                await websocket.send_json({"type": EventType.STATUS.value, "content": "Run cancelled", "phase": "idle"})
            except Exception as exc:
                logger.error("Chat run failed", error=str(exc), session=session.id)
                await websocket.send_json({"type": EventType.ERROR.value, "content": str(exc)})
            finally:
                current_run = None

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", session=session.id)
    except Exception as exc:
        logger.error("WebSocket handler crashed", error=str(exc))
        try:
            await websocket.send_json({"type": EventType.ERROR.value, "content": f"Server error: {exc}"})
        except Exception:
            pass
    finally:
        if current_run and not current_run.done():
            current_run.cancel()
        emitter.closed = True
        ws_gate.release(client_host)

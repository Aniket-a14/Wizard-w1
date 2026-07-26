"""Per-session state.

The API previously kept ``state = {"df": None, "catalog": None}`` at module
scope and pointed every request at one shared sandbox container. Two browsers
hitting the same server overwrote each other's dataset, and because the sandbox
namespace persisted between executions, one user's variables were readable by
the next. That is the blocker for "usable by anyone".

Each session owns:

* its datasets (multiple files, one active)
* its semantic catalog and schema registrations
* its conversation history
* its sandbox container and workspace directory

Sessions are reaped on a TTL, and the oldest is evicted when the active cap is
reached so a public deployment cannot be made to spawn unbounded containers.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings
from src.core.database import db_mgr
from src.core.execution import CodeExecutor
from src.core.ingest.loader import safe_write_feather
from src.core.tools.sandbox import sandbox_pool
from src.utils.logging import logger


@dataclass
class DatasetHandle:
    """One loaded table belonging to a session."""

    name: str
    df: pd.DataFrame
    catalog: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    source_format: str = "csv"
    loaded_at: float = field(default_factory=time.time)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rows": int(len(self.df)),
            "columns": list(map(str, self.df.columns)),
            "column_count": int(len(self.df.columns)),
            "source_format": self.source_format,
            "profile": self.profile,
            "loaded_at": self.loaded_at,
        }


@dataclass
class ModelPreferences:
    """User-selected models. ``None`` means "use the configured default".

    The provider is tracked *per role*, not once for the session, so a user can
    plan on an Ollama reasoning model and generate code on an LM Studio one.
    Sessions that never touch the provider fields behave exactly as before,
    running everything on ``settings.API_PROVIDER``.
    """

    manager: str | None = None
    worker: str | None = None
    vision: str | None = None
    temperature: float | None = None
    manager_provider: str | None = None
    worker_provider: str | None = None
    vision_provider: str | None = None

    def model_for(self, role: str) -> str | None:
        return getattr(self, role, None)

    def provider_for(self, role: str) -> str | None:
        return getattr(self, f"{role}_provider", None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manager": self.manager,
            "worker": self.worker,
            "vision": self.vision,
            "temperature": self.temperature,
            "manager_provider": self.manager_provider,
            "worker_provider": self.worker_provider,
            "vision_provider": self.vision_provider,
        }


class Session:
    def __init__(self, session_id: str):
        self.id = session_id
        self.created_at = time.time()
        self.last_seen = time.time()
        self.datasets: dict[str, DatasetHandle] = {}
        self.active_dataset: str | None = None
        self.models = ModelPreferences()
        self.executor = CodeExecutor(session_id)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def touch(self):
        self.last_seen = time.time()

    @property
    def workspace(self) -> Path:
        return sandbox_pool.workspace_for(self.id)

    @property
    def df(self) -> pd.DataFrame | None:
        handle = self.active_handle
        return handle.df if handle else None

    @property
    def catalog(self) -> dict[str, Any] | None:
        handle = self.active_handle
        return handle.catalog if handle else None

    @property
    def active_handle(self) -> DatasetHandle | None:
        if self.active_dataset is None:
            return None
        return self.datasets.get(self.active_dataset)

    @property
    def has_data(self) -> bool:
        return self.active_handle is not None

    # ------------------------------------------------------------------ #
    def add_dataset(
        self,
        name: str,
        df: pd.DataFrame,
        catalog: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
        source_format: str = "csv",
        make_active: bool = True,
    ) -> DatasetHandle:
        """Registers a dataset and materialises it into the session workspace."""
        handle = DatasetHandle(
            name=name,
            df=df,
            catalog=catalog or {},
            profile=profile or {},
            source_format=source_format,
        )
        with self._lock:
            self.datasets[name] = handle
            if make_active or self.active_dataset is None:
                self.active_dataset = name
        self.touch()
        self._materialize(handle, is_active=self.active_dataset == name)
        return handle

    def set_active(self, name: str) -> bool:
        handle = self.datasets.get(name)
        if handle is None:
            return False
        with self._lock:
            self.active_dataset = name
        self._materialize(handle, is_active=True)
        self.executor.reload_dataset()
        return True

    def remove_dataset(self, name: str) -> bool:
        with self._lock:
            handle = self.datasets.pop(name, None)
            if handle is None:
                return False
            if self.active_dataset == name:
                self.active_dataset = next(iter(self.datasets), None)
        db_mgr.delete_schema(name, session_id=self.id)
        for suffix in ("", ".feather"):
            (self.workspace / f"{name}{suffix}").unlink(missing_ok=True)
        return True

    def _materialize(self, handle: DatasetHandle, is_active: bool):
        """Writes the frame where the sandbox can read it.

        The active dataset is additionally written as ``dataset.feather``, which
        is the name the sandbox daemon preloads into ``df`` at startup.
        """
        workspace = self.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            handle.df.to_csv(workspace / handle.name, index=False)
            if is_active:
                dtypes_preserved = safe_write_feather(handle.df, workspace / "dataset.feather")
                handle.df.to_csv(workspace / "dataset.csv", index=False)
                if not dtypes_preserved:
                    logger.info(
                        "Some object columns were stringified for Feather transport",
                        dataset=handle.name,
                    )
        except Exception as exc:
            logger.error("Failed to materialize dataset into workspace", dataset=handle.name, error=str(exc))

    # ------------------------------------------------------------------ #
    def append_message(self, role: str, content: str, meta: dict[str, Any] | None = None):
        db_mgr.append_chat_message(self.id, role, content, meta)

    def history(self, limit: int | None = None) -> list[dict[str, Any]]:
        return db_mgr.get_chat_messages(self.id, limit=limit or settings.SESSION_HISTORY_TURNS * 2)

    def history_prompt(self, limit: int | None = None) -> str:
        """Renders recent turns for prompt injection. Empty when there is no history."""
        messages = self.history(limit)
        if not messages:
            return ""
        lines = []
        for message in messages:
            speaker = "User" if message["role"] == "user" else "Assistant"
            text = (message["content"] or "").strip()
            if len(text) > 400:
                text = text[:400] + "..."
            if text:
                lines.append(f"{speaker}: {text}")
        if not lines:
            return ""
        return "\n<conversation_history>\n" + "\n".join(lines) + "\n</conversation_history>\n"

    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "has_data": self.has_data,
            "active_dataset": self.active_dataset,
            "datasets": [handle.summary() for handle in self.datasets.values()],
            "models": self.models.to_dict(),
            "sandboxed": sandbox_pool.available,
        }

    def dispose(self):
        """Releases the container and forgets persisted rows for this session."""
        sandbox_pool.release(self.id)
        db_mgr.delete_session_data(self.id)
        with self._lock:
            self.datasets.clear()
            self.active_dataset = None


class SessionManager:
    """Owns the session lifecycle: creation, lookup, TTL reaping and eviction."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        session = Session(uuid.uuid4().hex)
        with self._lock:
            self._sessions[session.id] = session
        logger.info("Session created", session=session.id, active=len(self._sessions))
        self._enforce_capacity()
        return session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is not None:
            session.touch()
        return session

    def get_or_create(self, session_id: str | None = None) -> Session:
        """Resolves an id to a live session, creating one when it is absent or expired."""
        session = self.get(session_id)
        if session is not None:
            return session
        return self.create()

    def drop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.dispose()
        logger.info("Session dropped", session=session_id)
        return True

    def reap_expired(self) -> int:
        """Disposes sessions idle beyond the TTL. Returns how many were reaped."""
        cutoff = time.time() - settings.SESSION_TTL_SECONDS
        with self._lock:
            expired = [sid for sid, session in self._sessions.items() if session.last_seen < cutoff]
            sessions = [self._sessions.pop(sid) for sid in expired]
        for session in sessions:
            session.dispose()
        if sessions:
            logger.info("Reaped idle sessions", count=len(sessions))
        return len(sessions)

    def _enforce_capacity(self):
        """Evicts the least-recently-seen session past the configured cap."""
        with self._lock:
            overflow = len(self._sessions) - settings.SESSION_MAX_ACTIVE
            if overflow <= 0:
                return
            ordered = sorted(self._sessions.values(), key=lambda s: s.last_seen)
            victims = [self._sessions.pop(s.id) for s in ordered[:overflow]]
        for session in victims:
            logger.warning("Evicting session to stay within capacity", session=session.id)
            session.dispose()

    def shutdown(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            sandbox_pool.release(session.id)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def stats(self) -> dict[str, Any]:
        return {
            "active_sessions": self.active_count,
            "max_sessions": settings.SESSION_MAX_ACTIVE,
            "ttl_seconds": settings.SESSION_TTL_SECONDS,
            "sandbox_available": sandbox_pool.available,
            "active_sandboxes": sandbox_pool.active_count,
        }


session_manager = SessionManager()

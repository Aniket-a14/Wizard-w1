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

import re
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
from src.core.ingest.documents import ContextDocument, search_documents as rank_document_chunks
from src.core.ingest.loader import safe_write_feather
from src.core.tools import runtime as runtime_backend
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

    @property
    def table_key(self) -> str:
        """The name this table is exposed under in the sandbox's ``tables`` dict.

        Derived from the filename with the extension and any path-unsafe
        character removed, so ``Q3 sales (final).csv`` becomes ``q3_sales_final``
        — addressable from generated code and safe as a filename.
        """
        stem = Path(self.name).stem.strip().lower()
        cleaned = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
        return cleaned or "table"

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table_key": self.table_key,
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
        self.documents: dict[str, ContextDocument] = {}
        self.active_dataset: str | None = None
        self.models = ModelPreferences()
        self.executor = CodeExecutor(session_id)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def touch(self):
        self.last_seen = time.time()

    @property
    def workspace(self) -> Path:
        return runtime_backend.workspace_for(self.id)

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

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        """Every loaded table, keyed as generated code will address it.

        Mirrors what the sandbox daemon builds from the bind mount, so the
        Docker-less fallback presents the same namespace as the container.
        """
        return {handle.table_key: handle.df for handle in self.datasets.values()}

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
        (self.workspace / "tables" / f"{handle.table_key}.feather").unlink(missing_ok=True)
        # The daemon holds the removed frame in its `tables` dict until told
        # otherwise; without this it stays queryable after the user deleted it.
        self.executor.reload_dataset()
        return True

    def _materialize(self, handle: DatasetHandle, is_active: bool):
        """Writes the frame where the sandbox can read it.

        Every dataset is written as ``tables/<name>.feather``, which the daemon
        preloads into the ``tables`` dict, and the active one is additionally
        written as ``dataset.feather`` to become ``df``. Cross-table questions
        need every table in the namespace at once: previously only the active
        frame was loaded and the others were merely *mentioned* in the prompt as
        filenames the model might choose to read, which it usually did not, and
        got wrong when it did.
        """
        workspace = self.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        tables_dir = workspace / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        try:
            handle.df.to_csv(workspace / handle.name, index=False)
            safe_write_feather(handle.df, tables_dir / f"{handle.table_key}.feather")
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
    # Reference documents
    # ------------------------------------------------------------------ #
    @property
    def has_documents(self) -> bool:
        return bool(self.documents)

    def add_document(self, document: ContextDocument) -> ContextDocument:
        with self._lock:
            self.documents[document.name] = document
        self.touch()
        return document

    def remove_document(self, name: str) -> bool:
        with self._lock:
            return self.documents.pop(name, None) is not None

    def search_documents(self, query: str, limit: int | None = None) -> list[tuple[str, str]]:
        """Passages from the attached references that bear on ``query``."""
        if not self.documents:
            return []
        return rank_document_chunks(self.documents, query, limit)

    # ------------------------------------------------------------------ #
    # Deterministic inspection
    # ------------------------------------------------------------------ #
    def inspect(self, goal: str = "", max_columns: int = 60) -> str:
        """Describes the data without generating or running any code.

        Schema, null structure and value distributions are facts about a frame.
        Making the agent write and execute Python to discover them costs a code
        round-trip plus an execution for something pandas can answer directly --
        and it is the single most common thing an investigation needs first.
        """
        frame = self.df
        if frame is None:
            return "No dataset is loaded."

        from src.core.rag.retriever import context_retriever, mentions_column

        columns, truncated = context_retriever.select_columns(goal or "", frame, max_columns)
        lowered = (goal or "").lower()
        lines: list[str] = [
            f"Active table `{self.active_dataset}`: {len(frame):,} rows x {len(frame.columns)} columns."
        ]

        if len(self.datasets) > 1:
            others = ", ".join(f"`{name}` ({len(h.df):,} rows)" for name, h in self.datasets.items())
            lines.append(f"All loaded tables (available as `tables[...]`): {others}")

        if truncated:
            lines.append(f"Describing {len(columns)} of {len(frame.columns)} columns, chosen for relevance.")

        lines.append("\n| column | dtype | nulls | distinct | example |")
        lines.append("| --- | --- | --- | --- | --- |")
        for column in columns:
            series = frame[column]
            null_pct = (series.isna().mean() * 100) if len(frame) else 0.0
            try:
                distinct = int(series.nunique(dropna=True))
            except (TypeError, ValueError):
                distinct = -1
            try:
                example = str(series.dropna().iloc[0])[:40]
            except (IndexError, KeyError):
                example = ""
            distinct_text = "n/a" if distinct < 0 else f"{distinct:,}"
            lines.append(f"| {column} | {series.dtype} | {null_pct:.1f}% | {distinct_text} | {example} |")

        # The goal steers what detail is worth spending characters on.
        named = [c for c in columns if mentions_column(goal or "", c)]
        if named:
            lines.append("\nDistributions for the columns named in the request:")
            for column in named[:5]:
                lines.append(self._describe_column(frame, column))
        elif "null" in lowered or "missing" in lowered or "quality" in lowered:
            worst = frame[columns].isna().mean().sort_values(ascending=False).head(10)
            lines.append("\nMissingness, worst first:")
            lines.extend(f"- `{name}`: {rate:.1%} missing" for name, rate in worst.items() if rate > 0)
        else:
            lines.append("\nFirst rows:")
            try:
                lines.append(frame[columns].head(5).to_markdown(index=False))
            except Exception:
                lines.append(frame[columns].head(5).to_string())

        return "\n".join(lines)

    @staticmethod
    def _describe_column(frame: pd.DataFrame, column: str) -> str:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series):
            stats = series.describe()
            return (
                f"- `{column}`: min {stats.get('min'):,.4g}, median {series.median():,.4g}, "
                f"mean {stats.get('mean'):,.4g}, max {stats.get('max'):,.4g}, std {stats.get('std'):,.4g}"
            )
        try:
            counts = series.value_counts(dropna=True).head(8)
        except (TypeError, ValueError):
            return f"- `{column}`: values could not be counted."
        rendered = ", ".join(f"{value!r} ({count:,})" for value, count in counts.items())
        return f"- `{column}`: {series.nunique(dropna=True):,} distinct — {rendered}"

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
            "documents": [document.summary() for document in self.documents.values()],
            "models": self.models.to_dict(),
            "sandboxed": runtime_backend.active_backend() == "docker",
            "execution_backend": runtime_backend.active_backend(),
        }

    def dispose(self):
        """Releases the container and forgets persisted rows for this session."""
        runtime_backend.release_runtime(self.id)
        runtime_backend.forget_capabilities(self.id)
        db_mgr.delete_session_data(self.id)
        with self._lock:
            self.datasets.clear()
            self.documents.clear()
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
            runtime_backend.release_runtime(session.id)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def stats(self) -> dict[str, Any]:
        return {
            "active_sessions": self.active_count,
            "max_sessions": settings.SESSION_MAX_ACTIVE,
            "ttl_seconds": settings.SESSION_TTL_SECONDS,
            "execution_backend": runtime_backend.active_backend(),
            "active_runtimes": runtime_backend.active_runtime_count(),
        }


session_manager = SessionManager()

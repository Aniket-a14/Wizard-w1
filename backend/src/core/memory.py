"""Persistent working memory for the agent.

Scoped per session so one user's history never leaks into another's prompt, and
embedded on write so retrieval is semantic rather than the previous
``LIKE %term%`` scan (which matched on stopwords and ranked by recency only).
"""

from __future__ import annotations

import time
from typing import Any

from src.config import settings
from src.core.database import db_mgr
from src.core.embeddings import embedding_service
from src.utils.logging import logger


class WorkingMemory:
    """Thin façade over the ``working_memory`` table."""

    def add_interaction(
        self,
        instruction: str,
        plan: str,
        code: str,
        result: str,
        meta: dict[str, Any] | None = None,
        session_id: str | None = None,
    ):
        embedding = None
        try:
            embedding = embedding_service.encode(instruction.strip().lower())
        except Exception as exc:  # embedding is an optimisation, never a hard requirement
            logger.debug("Could not embed memory entry", error=str(exc))

        db_mgr.save_memory(
            timestamp=time.time(),
            instruction=instruction,
            plan=plan,
            code=code,
            result=result,
            meta=meta,
            session_id=session_id,
            embedding=embedding,
        )

    def search(self, query: str, limit: int = 3, session_id: str | None = None) -> list[dict[str, Any]]:
        return db_mgr.search_memories(query, limit=limit, session_id=session_id)

    def all(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return db_mgr.get_memories(session_id=session_id)

    def recent(self, timespan_seconds: int, session_id: str | None = None) -> list[dict[str, Any]]:
        return db_mgr.get_recent_memories(session_id=session_id, timespan_seconds=timespan_seconds)

    def get_context_string(self, query: str, session_id: str | None = None) -> str:
        """Prompt block of semantically relevant prior interactions."""
        from src.core.rag.retriever import context_retriever

        return context_retriever.build_context_block(query, session_id)

    def prune(self, keep_last: int = 500):
        db_mgr.prune_memories(keep_last=keep_last)

    @property
    def memories(self) -> list[dict[str, Any]]:
        """All stored interactions.

        Kept as a property because the SQLite migration removed the original
        in-memory list attribute of the same name while `ReportingEngine` was
        still reading it, which made `GET /report` raise `AttributeError`.
        """
        return db_mgr.get_memories()


working_memory = WorkingMemory()

__all__ = ["WorkingMemory", "working_memory", "settings"]

"""Store of confirmed-good task/code pairs used as few-shot examples."""

from __future__ import annotations

import json
import os

from src.config import settings
from src.core.database import db_mgr
from src.core.embeddings import embedding_service
from src.utils.logging import logger


class FeedbackStore:
    """SQLite-backed few-shot memory with semantic retrieval."""

    _legacy_synced = False

    def __init__(self, filename: str | None = None):
        self.filename = filename or settings.FEEDBACK_FILE
        # The legacy JSON import only needs to happen once per process; the
        # original ran it in every constructor, and three different components
        # construct this class.
        if not FeedbackStore._legacy_synced:
            self._sync_legacy_file()
            FeedbackStore._legacy_synced = True

    def _sync_legacy_file(self):
        if not self.filename or not os.path.exists(self.filename):
            return
        try:
            with open(self.filename, encoding="utf-8") as handle:
                payload = json.load(handle)
            for entry in payload.get("successful_examples", []):
                task, code = entry.get("task", ""), entry.get("code", "")
                if task and code:
                    db_mgr.save_feedback(task, code)
            logger.info("Imported legacy feedback file", path=self.filename)
        except Exception as exc:
            logger.debug("No legacy feedback imported", error=str(exc))

    # ------------------------------------------------------------------ #
    def add_example(self, example: dict):
        task, code = example.get("task", ""), example.get("code", "")
        if not task or not code:
            return
        embedding = None
        try:
            embedding = embedding_service.encode(task.strip().lower())
        except Exception:
            pass
        db_mgr.save_feedback(task, code, embedding)

    def get_similar_examples(self, query: str, limit: int = 2) -> list[dict]:
        """Highest-scoring stored examples for ``query``."""
        from src.core.rag.retriever import context_retriever

        return context_retriever.retrieve_examples(query, limit=limit)

    def all_examples(self) -> list[dict]:
        return [{"task": entry["task"], "code": entry["code"]} for entry in db_mgr.get_feedbacks()]

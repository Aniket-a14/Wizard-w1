"""Semantic cache for previously-successful code.

Repeat questions against the same schema skip planning and code generation
entirely, which is the difference between a 30-second and an instant answer on a
laptop running local models.

Two changes from the original: embedding work is delegated to the shared
:mod:`src.core.embeddings` service (so the model is loaded once process-wide
rather than per consumer), and a hot in-memory layer sits in front of SQLite so
a repeated query does not re-read and re-score every row.
"""

from __future__ import annotations

import hashlib

from src.config import settings
from src.core.database import db_mgr
from src.core.embeddings import embedding_service
from src.core.infra.cache import get_cache
from src.utils.logging import logger


class SemanticCache:
    def __init__(self, threshold: float | None = None):
        self.threshold = threshold if threshold is not None else settings.SEMANTIC_CACHE_THRESHOLD

    @staticmethod
    def _exact_key(query: str, columns: list[str]) -> str:
        digest = hashlib.blake2b(
            f"{query.strip().lower()}|{','.join(sorted(columns))}".encode(), digest_size=16
        ).hexdigest()
        return f"semcache:{digest}"

    # ------------------------------------------------------------------ #
    def lookup(self, query: str, active_columns: list[str]) -> str | None:
        """Returns cached code for a semantically equivalent query on the same schema."""
        if not query or not active_columns:
            return None

        cache = get_cache()
        exact = cache.get(self._exact_key(query, active_columns))
        if isinstance(exact, str) and exact:
            logger.info("Semantic cache hit (exact)")
            return exact

        entries = db_mgr.get_cache_entries(active_columns)
        if not entries:
            return None

        active = sorted(active_columns)
        # Schema equality is a hard precondition: code written for one column set
        # is not valid for another even if the questions are worded identically.
        candidates = [entry for entry in entries if sorted(entry.get("columns", [])) == active]
        if not candidates:
            return None

        ranked = embedding_service.rank(query.strip().lower(), [(c["query"], c.get("embedding")) for c in candidates])
        if not ranked:
            return None

        score, index = ranked[0]
        if score < self.threshold:
            logger.info("Semantic cache miss", best_similarity=round(score, 4))
            return None

        best = candidates[index]
        logger.info("Semantic cache hit", similarity=round(score, 4), cached_query=best["query"])
        cache.set(self._exact_key(query, active_columns), best["code"], ttl=3600)
        return best["code"]

    def add(self, query: str, active_columns: list[str], code: str):
        """Stores successful code against the query that produced it."""
        if not query or not code or not active_columns:
            return
        try:
            normalized = query.strip().lower()
            db_mgr.save_cache_entry(normalized, active_columns, code, embedding_service.encode(normalized))
            get_cache().set(self._exact_key(query, active_columns), code, ttl=3600)
        except Exception as exc:
            logger.error("Failed to store semantic cache entry", error=str(exc))

    def clear(self):
        db_mgr.clear_cache()
        get_cache().clear()

    def _get_model(self):
        """Retained for backwards compatibility with callers that reached for the model."""
        return embedding_service


semantic_cache = SemanticCache()

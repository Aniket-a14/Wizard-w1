import threading

import numpy as np

from src.core.database import db_mgr
from src.utils.logging import logger


class SemanticCache:
    """
    Local semantic cache utilizing sentence-transformers for fast query matching.
    Caches successfully executed code blocks on a per-dataset-schema basis using SQLite.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", threshold: float = 0.92):
        self.model_name = model_name
        self.threshold = threshold
        self.model = None  # Lazy-loaded
        self.lock = threading.Lock()

    def _get_model(self):
        """Lazy loads the embedding model to avoid blocking app boot."""
        if self.model is None:
            with self.lock:
                if self.model is None:
                    try:
                        logger.info("Initializing SentenceTransformer model for Semantic Cache", model=self.model_name)
                        from sentence_transformers import SentenceTransformer

                        # This will download the model to cache on first use
                        self.model = SentenceTransformer(self.model_name)
                    except Exception as e:
                        logger.error("Failed to load SentenceTransformer model", error=str(e))
                        raise e
        return self.model

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot_product / (norm_a * norm_b))

    def lookup(self, query: str, active_columns: list[str]) -> str | None:
        """
        Looks up a query in the cache database.
        Returns the cached code if a semantic match is found AND the dataset columns match.
        """
        entries = db_mgr.get_cache_entries(active_columns)
        if not entries:
            return None

        try:
            model = self._get_model()
            if not model:
                return None

            query_vector = model.encode(query.strip().lower())
            active_cols_sorted = sorted(active_columns)

            best_match = None
            max_sim = -1.0

            for entry in entries:
                # Check schema alignment first: columns must match exactly
                cached_cols_sorted = sorted(entry.get("columns", []))
                if active_cols_sorted != cached_cols_sorted:
                    continue

                cached_vector = entry.get("embedding")
                if cached_vector is None or len(cached_vector) == 0:
                    continue

                sim = self._cosine_similarity(query_vector, cached_vector)
                if sim > max_sim:
                    max_sim = sim
                    best_match = entry

            if max_sim >= self.threshold and best_match:
                logger.info("Semantic Cache HIT", similarity=round(max_sim, 4), query=best_match["query"])
                return best_match["code"]

            logger.info("Semantic Cache MISS", max_similarity=round(max_sim, 4) if max_sim > -1 else "None")
        except Exception as e:
            logger.error("Error during semantic cache lookup", error=str(e))

        return None

    def add(self, query: str, active_columns: list[str], code: str):
        """
        Adds a successfully executed query and its code block to the SQLite cache database.
        """
        try:
            model = self._get_model()
            if not model:
                return

            query_clean = query.strip().lower()
            query_vector = model.encode(query_clean)

            db_mgr.save_cache_entry(query_clean, active_columns, code, query_vector)
        except Exception as e:
            logger.error("Error during semantic cache add", error=str(e))


# Singleton instance
semantic_cache = SemanticCache()

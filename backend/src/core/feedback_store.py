import json

import numpy as np

from src.config import settings
from src.core.database import db_mgr


class FeedbackStore:
    """
    Manages successful examples (few-shots) utilizing SQLite database storage
    with semantic vector cosine similarity matching.
    """

    def __init__(self, filename=None):
        # Kept for backward compatibility but operations are offloaded to SQLite
        self.filename = filename or settings.FEEDBACK_FILE
        self._sync_legacy_file_to_db()

    def _sync_legacy_file_to_db(self):
        """Loads legacy JSON feedbacks into the SQLite database on startup if any exist."""
        import os

        if os.path.exists(self.filename):
            try:
                with open(self.filename, encoding="utf-8") as f:
                    data = json.load(f)
                successful = data.get("successful_examples", [])
                for entry in successful:
                    task = entry.get("task", "")
                    code = entry.get("code", "")
                    if task and code:
                        db_mgr.save_feedback(task, code)
            except Exception:
                pass

    def add_example(self, example: dict):
        """Add a successful example to the database."""
        task = example.get("task", "")
        code = example.get("code", "")
        if task and code:
            try:
                from src.core.semantic_cache import semantic_cache

                model = semantic_cache._get_model()
                embedding = model.encode(task.strip().lower()) if model else None
            except Exception:
                embedding = None
            db_mgr.save_feedback(task, code, embedding)

    def get_similar_examples(self, query: str, limit: int = 2) -> list[dict]:
        """Retrieves successful examples matching the query semantically from SQLite."""
        feedbacks = db_mgr.get_feedbacks()
        if not feedbacks:
            return []

        try:
            from src.core.semantic_cache import semantic_cache

            model = semantic_cache._get_model()
            if model:
                query_vector = model.encode(query.strip().lower())
                scored_examples = []

                for fb in feedbacks:
                    task = fb["task"]
                    code = fb["code"]
                    task_vector = fb.get("embedding")

                    if task_vector is None or len(task_vector) == 0:
                        task_vector = model.encode(task.strip().lower())
                        # Save embedding back
                        db_mgr.save_feedback(task, code, task_vector)

                    dot_product = float(np.dot(query_vector, task_vector))
                    norm_q = float(np.linalg.norm(query_vector))
                    norm_t = float(np.linalg.norm(task_vector))
                    sim = dot_product / (norm_q * norm_t) if norm_q > 0 and norm_t > 0 else 0.0
                    scored_examples.append((sim, {"task": task, "code": code}))

                scored_examples.sort(key=lambda x: x[0], reverse=True)
                return [entry for sim, entry in scored_examples[:limit]]
        except Exception:
            pass  # Fallback to keyword matching below

        query_terms = query.lower().split()
        scored_examples = []

        for fb in feedbacks:
            score = 0
            task = fb["task"]
            code = fb["code"]
            content = task.lower()
            for term in query_terms:
                if term in content:
                    score += 1
            if score > 0:
                scored_examples.append((score, {"task": task, "code": code}))

        scored_examples.sort(key=lambda x: x[0], reverse=True)
        return [entry for score, entry in scored_examples[:limit]]

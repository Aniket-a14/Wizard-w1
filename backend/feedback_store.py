import json
import numpy as np
from src.config import settings


class FeedbackStore:
    def __init__(self, filename=None):
        self.filename = filename or settings.FEEDBACK_FILE
        self.feedback_data = self._load_feedback()

    def _load_feedback(self):
        try:
            with open(self.filename, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"successful_examples": [], "failed_examples": []}

    def save_feedback(self):
        with open(self.filename, "w") as f:
            json.dump(self.feedback_data, f, indent=2)

    def add_example(self, example: dict):
        """Add an example and invalidate cache"""
        if example not in self.feedback_data["successful_examples"]:
            self.feedback_data["successful_examples"].append(example)
            self.save_feedback()

    def get_similar_examples(self, query: str, limit: int = 2) -> list[dict]:
        """Retrieves successful examples from the feedback file matching the query semantically."""
        if not self.feedback_data or "successful_examples" not in self.feedback_data or not self.feedback_data["successful_examples"]:
            return []
            
        try:
            # Dynamically load semantic cache model if available
            from src.core.semantic_cache import semantic_cache
            model = semantic_cache._get_model()
            if model:
                query_vector = model.encode(query.strip().lower())
                scored_examples = []
                
                for entry in self.feedback_data["successful_examples"]:
                    task_text = entry.get("task", "").strip().lower()
                    if not task_text:
                        continue
                    task_vector = model.encode(task_text)
                    
                    # Cosine similarity
                    dot_product = float(np.dot(query_vector, task_vector))
                    norm_q = float(np.linalg.norm(query_vector))
                    norm_t = float(np.linalg.norm(task_vector))
                    sim = dot_product / (norm_q * norm_t) if norm_q > 0 and norm_t > 0 else 0.0
                    scored_examples.append((sim, entry))
                    
                scored_examples.sort(key=lambda x: x[0], reverse=True)
                return [entry for sim, entry in scored_examples[:limit]]
        except Exception:
            pass # Fallback to keyword matching below

        query_terms = query.lower().split()
        scored_examples = []
        
        for entry in self.feedback_data["successful_examples"]:
            score = 0
            task = entry.get("task", "")
            content = task.lower()
            for term in query_terms:
                if term in content:
                    score += 1
            if score > 0:
                scored_examples.append((score, entry))
        
        scored_examples.sort(key=lambda x: x[0], reverse=True)
        return [entry for score, entry in scored_examples[:limit]]


# this block of code is used to save the feedback to a json file
# the feedback is saved to a json file
# the feedback is used in the agent.py file to train the agent

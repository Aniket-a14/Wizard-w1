import json


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
        """Retrieves successful examples from the feedback file matching the query."""
        if not self.feedback_data or "successful_examples" not in self.feedback_data:
            return []
        
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

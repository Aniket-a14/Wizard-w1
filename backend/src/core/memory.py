import time
from typing import Any

from src.core.database import db_mgr
from src.utils.logging import logger


class WorkingMemory:
    """
    Handles persistent storage and retrieval of agent interactions.
    Uses SQLite via DatabaseManager for thread-safe concurrent access.
    """

    def __init__(self):
        pass

    def add_interaction(self, instruction: str, plan: str, code: str, result: str, meta: dict[str, Any] = None):
        """Adds a new interaction to memory (persisted to SQLite)."""
        ts = time.time()
        db_mgr.save_memory(ts, instruction, plan, code, result, meta)
        logger.info("New interaction saved to memory")

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Retrieves relevant past interactions based on a query directly from SQLite."""
        return db_mgr.search_memories(query, limit)

    def get_context_string(self, query: str) -> str:
        """Returns a formatted string of relevant past interactions."""
        relevant = self.search(query)
        if not relevant:
            return ""

        context = "\n--- Past Interaction Context ---\n"
        for entry in relevant:
            context += f"Previous Request: {entry['instruction']}\n"
            context += f"Key Finding: {entry['result'][:150]}...\n\n"
        return context


# Global Memory Instance initialized with SQLite-backed persistent store
working_memory = WorkingMemory()

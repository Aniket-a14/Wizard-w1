import time
from typing import List, Dict, Any, Optional
from src.utils.logging import logger
from src.core.database import db_mgr

class WorkingMemory:
    """
    Handles persistent storage and retrieval of agent interactions.
    Uses SQLite via DatabaseManager for thread-safe concurrent access.
    """
    
    def __init__(self):
        self.memories = db_mgr.get_memories()

    def add_interaction(self, instruction: str, plan: str, code: str, result: str, meta: Dict[str, Any] = None):
        """Adds a new interaction to memory (persisted to SQLite)."""
        ts = time.time()
        memory_entry = {
            "timestamp": ts,
            "instruction": instruction,
            "plan": plan,
            "code": code,
            "result": result,
            "meta": meta or {}
        }
        self.memories.append(memory_entry)
        db_mgr.save_memory(ts, instruction, plan, code, result, meta)
        logger.info("New interaction saved to memory", interaction_count=len(self.memories))

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Retrieves relevant past interactions based on a query."""
        query_terms = query.lower().split()
        scored_memories = []
        
        for entry in self.memories:
            score = 0
            content = f"{entry['instruction']} {entry['plan']}".lower()
            for term in query_terms:
                if term in content:
                    score += 1
            if score > 0:
                scored_memories.append((score, entry))
        
        scored_memories.sort(key=lambda x: (x[0], x[1]['timestamp']), reverse=True)
        return [entry for score, entry in scored_memories[:limit]]

    def get_context_string(self, query: str) -> str:
        """Returns a formatted string of relevant past interactions."""
        relevant = self.search(query)
        if not relevant:
            return ""
            
        context = "\n--- Past Interaction Context ---\n"
        for i, entry in enumerate(relevant):
            context += f"Previous Request: {entry['instruction']}\n"
            context += f"Key Finding: {entry['result'][:150]}...\n\n"
        return context

# Global Memory Instance initialized with SQLite-backed persistent store
working_memory = WorkingMemory()

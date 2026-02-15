import json
import os
import time
from typing import List, Dict, Any, Optional, Protocol
from src.utils.logging import logger

class MemoryStore(Protocol):
    """Protocol for memory storage backends."""
    def save(self, memories: List[Dict[str, Any]]): ...
    def load(self) -> List[Dict[str, Any]]: ...

class JSONMemoryStore:
    """JSON implementation of the memory store."""
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        if not os.path.exists(self.storage_path):
            with open(self.storage_path, 'w') as f:
                json.dump([], f)

    def save(self, memories: List[Dict[str, Any]]):
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(memories, f, indent=2)
        except Exception as e:
            logger.error("Failed to save memory", error=str(e))

    def load(self) -> List[Dict[str, Any]]:
        try:
            if not os.path.exists(self.storage_path):
                return []
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load memory", error=str(e))
            return []

class WorkingMemory:
    """
    Handles persistent storage and retrieval of agent interactions.
    Now supports abstract storage backends for professional scalability.
    """
    
    def __init__(self, store: Optional[MemoryStore] = None):
        # Default to JSON for now, but easily swappable
        self.store = store or JSONMemoryStore("backend/data/memory.json")
        self.memories = self.store.load()

    def add_interaction(self, instruction: str, plan: str, code: str, result: str, meta: Dict[str, Any] = None):
        """Adds a new interaction to memory."""
        memory_entry = {
            "timestamp": time.time(),
            "instruction": instruction,
            "plan": plan,
            "code": code,
            "result": result,
            "meta": meta or {}
        }
        self.memories.append(memory_entry)
        self.store.save(self.memories)
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

# Global Memory Instance initialized with default persistent store
working_memory = WorkingMemory()

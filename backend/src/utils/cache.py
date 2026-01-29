from typing import Any, Optional
import hashlib

class SimpleCache:
    """
    In-memory LRU-style cache for Agent Responses.
    Production: Replace dictionary with Redis.
    """
    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self.cache = {}
        self.order = [] # Track usage order

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            # Move to end (recently used)
            self.order.remove(key)
            self.order.append(key)
            return self.cache[key]
        return None

    def set(self, key: str, value: Any):
        if key in self.cache:
            self.order.remove(key)
        
        self.cache[key] = value
        self.order.append(key)
        
        if len(self.order) > self.capacity:
            oldest = self.order.pop(0)
            del self.cache[oldest]
            
    def generate_key(self, *args) -> str:
        """Generates a stable key from arguments."""
        content = "-".join(str(arg) for arg in args)
        return hashlib.md5(content.encode()).hexdigest()

response_cache = SimpleCache()

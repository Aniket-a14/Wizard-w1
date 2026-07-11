import json
import os
import threading
from typing import Optional, List, Dict, Any
import numpy as np
from src.config import settings
from src.utils.logging import logger

class SemanticCache:
    """
    Local semantic cache utilizing sentence-transformers for fast query matching.
    Caches successfully executed code blocks on a per-dataset-schema basis.
    """
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", threshold: float = 0.92):
        self.model_name = model_name
        self.threshold = threshold
        self.cache_file = settings.DATA_DIR / "semantic_cache.json"
        
        self.model = None  # Lazy-loaded
        self.entries: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        
        self._load_cache()

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

    def _load_cache(self):
        """Loads cached entries from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
                logger.info("Semantic cache loaded successfully", entries_count=len(self.entries))
            except Exception as e:
                logger.error("Failed to load semantic cache file", error=str(e))
                self.entries = []

    def _save_cache(self):
        """Saves current cache entries to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
            logger.info("Semantic cache saved to disk", entries_count=len(self.entries))
        except Exception as e:
            logger.error("Failed to save semantic cache file", error=str(e))

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot_product / (norm_a * norm_b))

    def lookup(self, query: str, active_columns: List[str]) -> Optional[str]:
        """
        Looks up a query in the cache. 
        Returns the cached code if a semantic match is found AND the dataset columns match.
        """
        if not self.entries:
            return None
            
        try:
            model = self._get_model()
            if not model:
                return None
                
            query_vector = model.encode(query.strip().lower())
            active_cols_sorted = sorted(active_columns)
            
            best_match = None
            max_sim = -1.0
            
            with self.lock:
                for entry in self.entries:
                    # Check schema alignment first: columns must match exactly
                    cached_cols_sorted = sorted(entry.get("columns", []))
                    if active_cols_sorted != cached_cols_sorted:
                        continue
                        
                    cached_vector = np.array(entry.get("embedding", []))
                    if len(cached_vector) == 0:
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

    def add(self, query: str, active_columns: List[str], code: str):
        """
        Adds a successfully executed query and its code block to the cache.
        """
        try:
            model = self._get_model()
            if not model:
                return
                
            query_clean = query.strip().lower()
            query_vector = model.encode(query_clean)
            
            new_entry = {
                "query": query_clean,
                "columns": active_columns,
                "code": code,
                "embedding": query_vector.tolist()
            }
            
            with self.lock:
                # Check if this query is already in the cache, if so, update the code
                for i, entry in enumerate(self.entries):
                    if entry["query"] == query_clean and sorted(entry.get("columns", [])) == sorted(active_columns):
                        self.entries[i]["code"] = code
                        self._save_cache()
                        return
                
                # Append new entry
                self.entries.append(new_entry)
                self._save_cache()
        except Exception as e:
            logger.error("Error during semantic cache add", error=str(e))

# Singleton instance
semantic_cache = SemanticCache()

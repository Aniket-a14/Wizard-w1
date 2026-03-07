import os
from typing import List, Dict, Any, Optional
from src.utils.logging import logger

class WebSearchTool:
    """
    Provides a unified interface for web search capabilities.
    Supports multiple backends (DuckDuckGo, Tavily, etc.)
    """
    def __init__(self, backend: str = "duckduckgo"):
        self.backend = backend
        logger.info("Initializing WebSearchTool", backend=backend)

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Performs a web search and returns a list of results.
        """
        logger.info("Performing web search", query=query, backend=self.backend)
        
        if self.backend == "duckduckgo":
            return self._duckduckgo_search(query, num_results)
        return []

    def _duckduckgo_search(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """
        Internal implementation using DuckDuckGo (requires 'duckduckgo-search' package).
        """
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results))
                return [
                    {
                        "title": r.get("title"),
                        "link": r.get("href"),
                        "snippet": r.get("body")
                    }
                    for r in results
                ]
        except ImportError:
            logger.warning("duckduckgo-search package not installed. Returning mock results.")
            return self._get_mock_results(query)
        except Exception as e:
            logger.error("DuckDuckGo search failed", error=str(e))
            return []

    def _get_mock_results(self, query: str) -> List[Dict[str, Any]]:
        """Fallback mock results for development without internet/library."""
        return [
            {
                "title": f"Documentation for {query}",
                "link": "https://docs.python.org/3/",
                "snippet": f"This is a placeholder result for '{query}'. Please install 'duckduckgo-search' for real results."
            }
        ]

# Simple singleton
web_search = WebSearchTool()

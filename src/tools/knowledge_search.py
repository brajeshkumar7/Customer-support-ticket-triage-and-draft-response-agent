"""Allowlisted, logged hybrid PDF search tool."""
from src.knowledge.store import KnowledgeStore
from src.tools.base import BaseTool


class KnowledgeSearchTool(BaseTool):
    tool_name = "knowledge_search"

    def __init__(self, store=None):
        self.store = store

    def _execute(self, *, query: str, top_k: int = 5):
        if self.store is None:
            self.store = KnowledgeStore()
        return {"evidence": self.store.search(query, top_k=top_k), "retrieval": "dense_bm25_rrf"}

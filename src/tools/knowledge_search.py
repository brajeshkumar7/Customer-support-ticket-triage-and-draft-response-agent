"""Allowlisted, logged hybrid PDF search tool."""
from src.knowledge.store import KnowledgeStore
from src.tools.base import BaseTool
from src.knowledge.policy import is_active_policy_chunk, policy_configuration


class KnowledgeSearchTool(BaseTool):
    tool_name = "knowledge_search"

    def __init__(self, store=None):
        self.store = store

    def _execute(self, *, query: str, top_k: int = 5):
        if self.store is None:
            self.store = KnowledgeStore()
        configuration = policy_configuration()
        candidates = self.store.search(query, top_k=12)
        evidence = [item for item in candidates if is_active_policy_chunk(item, configuration)][:top_k]
        return {"evidence": evidence, "retrieval": "dense_bm25_rrf"}

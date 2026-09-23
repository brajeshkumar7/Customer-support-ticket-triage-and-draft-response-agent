"""Keyword search over a small set of local support FAQs."""

import re
from typing import Any

from src.tools.base import BaseTool, ToolInputError

FAQ_ENTRIES = (
    {
        "id": "shipping-status",
        "question": "How can I track my shipment?",
        "answer": "Use the tracking link in the shipping confirmation email to view the latest carrier status.",
        "keywords": {"shipping", "shipment", "tracking", "track", "package", "delivery"},
    },
    {
        "id": "shipping-delay",
        "question": "What should I do if a shipment is delayed?",
        "answer": "Carrier scans can pause during transit. If the expected delivery window has passed, contact support with your order number.",
        "keywords": {"late", "delay", "delayed", "missing", "package", "carrier"},
    },
    {
        "id": "return-window",
        "question": "When can I return an item?",
        "answer": "Delivered items may be eligible for return within 30 days, subject to the return policy and item condition.",
        "keywords": {"return", "refund", "exchange", "window", "days", "eligible"},
    },
    {
        "id": "damaged-item",
        "question": "What if an item arrives damaged?",
        "answer": "Report damage within 7 days of delivery and include your order number and a description of the issue.",
        "keywords": {"damaged", "damage", "broken", "defective", "replacement"},
    },
    {
        "id": "refund-timing",
        "question": "How long does a refund take?",
        "answer": "After a refund is approved, the payment provider may take 5 to 10 business days to post it.",
        "keywords": {"refund", "money", "payment", "credited", "processing"},
    },
    {
        "id": "payment-methods",
        "question": "Which payment methods are accepted?",
        "answer": "Available payment methods are shown at checkout before an order is placed.",
        "keywords": {"payment", "card", "billing", "checkout", "accepted"},
    },
)
_STOP_WORDS = {"a", "an", "and", "are", "can", "do", "for", "i", "is", "it", "my", "of", "the", "to", "what", "when", "where"}


class FAQSearchTool(BaseTool):
    tool_name = "faq_search"

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolInputError(self.tool_name, "query must be a non-empty string.")

        query_terms = set(re.findall(r"[a-z0-9]+", query.lower())) - _STOP_WORDS
        ranked: list[tuple[int, dict[str, Any]]] = []
        for entry in FAQ_ENTRIES:
            searchable = set(entry["keywords"])
            searchable.update(re.findall(r"[a-z0-9]+", entry["question"].lower()))
            score = len(query_terms & searchable)
            if score:
                ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        matches = [
            {
                "id": entry["id"],
                "question": entry["question"],
                "answer": entry["answer"],
                "matched_terms": sorted(query_terms & (set(entry["keywords"]) | set(re.findall(r"[a-z0-9]+", entry["question"].lower())))),
            }
            for _, entry in ranked[:3]
        ]
        return {"matches": matches}

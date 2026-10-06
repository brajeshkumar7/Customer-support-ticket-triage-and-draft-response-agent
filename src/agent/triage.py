"""Stable urgency and priority derivation for support-ticket triage."""

from __future__ import annotations

import re
from typing import Any


URGENCY_PRIORITY = {
    "high": ("P1", 1),
    "medium": ("P2", 2),
    "low": ("P3", 3),
}

# Explicit signals that should put a ticket in the highest review band,
# regardless of the model's lower urgency suggestion.
HIGH_PRIORITY_PATTERN = re.compile(
    r"\b(?:urgent|urgently|asap|immediately|right away|deadline|"
    r"need(?:ed)?\s+(?:by|before)\s+today|need\s+.{0,35}\bby\s+today|"
    r"(?:event|appointment|flight|trip)\s+today|"
    r"manager|supervisor|injur(?:y|ed)|burn(?:ed|ing)?|spark(?:s|ed|ing)?|"
    r"electric shock|caught fire|smok(?:e|es|ed|ing)|overheat(?:s|ed|ing)?|"
    r"fraud|chargeback|unauthorized|stolen|hacked|emergency|legal action)\b",
    re.IGNORECASE,
)
MEDIUM_PRIORITY_PATTERN = re.compile(
    r"\b(?:angry|unacceptable|second time|again|still waiting|very upset|"
    r"disappointed|complaint|damaged|broken|defective|billing dispute|"
    r"duplicate charge|missing refund)\b",
    re.IGNORECASE,
)
BILLING_INTENT_PATTERN = re.compile(
    r"\b(?:unrecognized|unauthorized|duplicate|unexpected)\s+(?:card\s+)?"
    r"(?:charge|payment|transaction)|\bcharged\s+twice\b|"
    r"\b(?:payment|charge|transaction)\b.{0,70}\b(?:missing|not\s+recognized|"
    r"did\s+not\s+authorize|without\s+permission|no\s+(?:order\s+)?confirmation|"
    r"did\s+not\s+receive\s+(?:an\s+)?(?:order\s+)?confirmation|"
    r"purchase\s+went\s+through|find\s+(?:the\s+)?transaction|disput\w*)|"
    r"\b(?:partial|missing|unreceived|unposted)\s+refund\b|"
    r"\brefund\b.{0,70}\b(?:missing|not\s+(?:arrived|posted|appeared)|partial)\b|"
    r"\b(?:tax|invoice)\b.{0,70}\b(?:wrong|incorrect|disput\w*|mismatch|difference)\b",
    re.IGNORECASE,
)
RETURN_INTENT_PATTERN = re.compile(
    r"\b(?:return|returns|returning|exchange|exchanges|warranty|"
    r"return\s+window|return\s+policy)\b",
    re.IGNORECASE,
)
DAMAGE_INTENT_PATTERN = re.compile(
    r"\b(?:damaged?|broken|cracked|defective|defect|sparks?|"
    r"smok(?:e|es|ed|ing)|overheat(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
PRODUCT_MALFUNCTION_PATTERN = re.compile(
    r"\b(?:my|the)\s+(?:[a-z0-9-]+\s+){0,3}"
    r"(?:item|product|device|blender|speaker|lamp|headphones|charger|"
    r"phone|laptop|appliance)\b.{0,50}\b(?:stopped\s+working|"
    r"not\s+working|isn['’]?t\s+working|doesn['’]?t\s+work|does\s+not\s+work)\b",
    re.IGNORECASE,
)
ORDER_STATUS_INTENT_PATTERN = re.compile(
    r"\b(?:where\s+(?:is|['’]s)\s+(?:my\s+)?(?:order|package|parcel|shipment)|"
    r"(?:order|package|parcel|shipment)\s+(?:status|tracking)|"
    r"(?:track|tracking)\s+(?:my|the)\s+(?:order|package|parcel|shipment)|"
    r"(?:hasn['’]?t|has\s+not|never)\s+arrived|delivery\s+status)\b",
    re.IGNORECASE,
)


def reconcile_category(ticket_text: str, model_category: str) -> tuple[str, str]:
    """Correct clear model category misses with specific ticket intent cues."""
    text = ticket_text
    if BILLING_INTENT_PATTERN.search(text):
        return "billing dispute", "explicit_billing_intent"
    if RETURN_INTENT_PATTERN.search(text):
        return "return request", "explicit_return_intent"
    if DAMAGE_INTENT_PATTERN.search(text) or PRODUCT_MALFUNCTION_PATTERN.search(text):
        return "damaged item", "explicit_damage_intent"
    if ORDER_STATUS_INTENT_PATTERN.search(text):
        return "order status", "explicit_order_status_intent"
    return model_category, "llm_classification"


def derive_triage(
    ticket_text: str,
    *,
    model_urgency: str,
    classification_basis: str,
    category_basis: str,
) -> dict[str, Any]:
    """Return normalized urgency and a sortable priority with its basis.

    High-risk/explicitly time-critical wording is a deterministic override.
    Otherwise the validated classifier urgency is retained. Priority bands
    are ordering labels only; they do not promise an SLA or trigger a queue.
    """
    urgency = model_urgency.strip().lower()
    if urgency not in URGENCY_PRIORITY:
        raise ValueError("Urgency must be low, medium, or high.")

    if HIGH_PRIORITY_PATTERN.search(ticket_text):
        urgency = "high"
        urgency_basis = "explicit_high_priority_signal"
    elif urgency == "low" and MEDIUM_PRIORITY_PATTERN.search(ticket_text):
        urgency = "medium"
        urgency_basis = "explicit_medium_priority_signal"
    else:
        urgency_basis = "classifier_urgency"

    priority, rank = URGENCY_PRIORITY[urgency]
    return {
        "urgency": urgency,
        "priority": priority,
        "priority_rank": rank,
        "classification_basis": classification_basis,
        "category_basis": category_basis,
        "urgency_basis": urgency_basis,
    }

"""Versioned, deterministic public-reply policy for controlled deployment."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from src.agent.safety import (
    AMBIGUITY_PATTERN,
    BILLING_DISPUTE_PATTERN,
    MANAGER_PATTERN,
    POLICY_EXCEPTION_PATTERN,
    SAFETY_PATTERN,
)

KNOWLEDGE_PATH = Path(__file__).resolve().parents[2] / "data" / "approved_knowledge" / "v1.json"
APPROVAL_POLICY_VERSION = "informational_only_v3"
HIGH_STAKES = re.compile(r"\b(?:lawsuit|lawyer|legal action|regulator|fraud|chargeback|police|emergency|threaten|hacked|compromised|stolen|unauthorized)\b", re.I)
SENSITIVE_REQUEST = re.compile(r"\b(?:cvv|full card|credit card number|password|api key|bank account|identity document)\b", re.I)
UNSUPPORTED_ACTION = re.compile(
    r"\b(?:investigate|look into|contact (?:the )?carrier|open (?:a )?(?:case|investigation)|"
    r"send me|give me|provide (?:me|my)|reship|ship (?:my|the)|trace (?:my|the)|"
    r"check (?:on|my|the))\b",
    re.I,
)
APPROVED_REFUND_CONTEXT = re.compile(
    r"\b(?:approved\s+refund|refund\s+(?:(?:has|had)\s+)?(?:already\s+)?"
    r"(?:been\s+)?approved|refund\s+is\s+approved)\b",
    re.I,
)
SECOND_REQUEST = re.compile(
    r"(?:[?;]\s*|\b(?:and|also|plus)\s+)"
    r"(?:can|could|do|does|did|is|are|will|would|what|how|when|where|why|please|i\s+(?:need|want))\b",
    re.I,
)
SUPPORTED_CARRIER_FOLLOWUP = re.compile(
    r"\band\s+what\s+(?:(?:should|can)\s+i\s+do\s+)?if\s+"
    r"(?:the\s+)?(?:expected\s+|estimated\s+)?delivery\s+"
    r"(?:window|date)\s+(?:passes|goes\s+by)\b",
    re.I,
)


@dataclass(frozen=True)
class ReplyDecision:
    kind: str
    reason: str
    body: str | None = None
    knowledge_version: str | None = None
    reason_code: str = ""
    evidence_ids: tuple[str, ...] = ()
    policy_version: str = APPROVAL_POLICY_VERSION


def approved_knowledge(path: Path = KNOWLEDGE_PATH) -> dict:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    expected = os.getenv("APPROVED_KNOWLEDGE_SHA256", "").strip().lower()
    if not expected or expected != actual:
        raise ValueError("Approved knowledge hash is missing or does not match the reviewed file.")
    data = json.loads(raw)
    if data.get("status") != "approved" or data.get("version") != "v1":
        raise ValueError("Knowledge file requires owner approval and a supported version.")
    return data


def simulation_knowledge(path: Path = KNOWLEDGE_PATH) -> dict:
    """Load local example content for fake-sender runs, never live delivery."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "review_required" or data.get("version") != "v1":
        raise ValueError("The local simulation knowledge file has an unexpected version or status.")
    return data


def decide_public_reply(ticket_text: str, *, knowledge: dict) -> ReplyDecision:
    """Allow only narrow informational requests; return no LLM prose for sending."""
    text = ticket_text.casefold()
    def human(code: str, reason: str) -> ReplyDecision:
        return ReplyDecision("human", reason, reason_code=code)

    if (not isinstance(knowledge, dict)
            or knowledge.get("status") not in {"review_required", "approved"}
            or not isinstance(knowledge.get("version"), str)
            or not knowledge["version"].strip()):
        return human("knowledge_unavailable", "Versioned local knowledge is unavailable.")
    if not text.strip():
        return human("empty_ticket", "The ticket has no usable message.")
    if HIGH_STAKES.search(text) or SENSITIVE_REQUEST.search(text):
        return human("high_stakes_or_sensitive", "Legal, fraud, emergency, or sensitive credentials require human review.")
    if any(pattern.search(text) for pattern in (
        SAFETY_PATTERN, MANAGER_PATTERN, POLICY_EXCEPTION_PATTERN,
        BILLING_DISPUTE_PATTERN, AMBIGUITY_PATTERN,
    )):
        return human("human_judgment_required", "Safety, billing, ambiguity, or a discretionary action requires a person.")
    if re.search(r"\b(?:refund me|issue (?:me )?a refund|cancel|replace|exchange|approve|change my|update my|edit my|correct my|change the|update the)\b", text):
        return human("business_action_unavailable", "The customer requests a business action this agent cannot perform.")
    if UNSUPPORTED_ACTION.search(text):
        return human("business_action_unavailable", "The customer requests an investigation or action this agent cannot perform.")
    # An order number, customer identity, delivery assertion, or account detail
    # needs an authoritative, fresh provider and verified requester identity.
    generic_refund_timing = bool(
        re.search(r"\b(?:refund|credited)\b", text)
        and APPROVED_REFUND_CONTEXT.search(text)
        and re.search(r"\b(?:how long|how many|usual|typically|business days)\b", text)
        and not re.search(r"\b(?:check|verify|confirm|status|where is|has it)\b", text)
    )
    if re.search(r"\bORD-\d+\b", text, re.I) or re.search(
        r"\b(?:my order status|where is my order|my package has not arrived|"
        r"my refund status|was my refund approved|was i charged)\b", text
    ) or re.search(r"\bmy (?:order|package|parcel|shipment|address|payment|card|tracking link|tracking number)\b", text) or (
        ("my account" in text or "my refund" in text) and not generic_refund_timing
    ):
        return human("customer_facts_unverified", "Customer-specific facts lack authoritative source and identity verification.")

    # A generic FAQ must not be used to quote an undocumented service, price,
    # guarantee, or merchant commitment. Each approved reply covers one intent.
    if re.search(r"\b(?:overnight|same.day|international|guaranteed|price|cost|rate|fee|promise)\b", text):
        return human("merchant_terms_unavailable", "No approved knowledge covers the requested merchant service, price, or guarantee.")

    matches: list[str] = []
    if re.search(r"\b(?:refund|credited)\b", text) and re.search(r"\b(?:how long|how many|when|usual|typically|timing|post|business days)\b", text):
        matches.append("refund_timing")
    if re.search(r"\b(?:carrier|scans?|tracking)\b", text) and re.search(r"\b(?:delay|late|unchanged|not changed|hasn't changed|paused|delivery window|expected delivery)\b", text):
        matches.append("carrier_delay")
    if re.search(r"\b(?:tracking link|track my shipment|find tracking)\b", text):
        matches.append("tracking_link")
    if re.search(r"\b(?:payment methods|ways to pay|which cards|pay at checkout)\b", text):
        matches.append("payment_methods")
    if len(matches) != 1:
        return human("faq_coverage_missing", "No single approved informational reply covers the entire request.")
    reply_type = matches[0]
    if reply_type == "refund_timing" and not APPROVED_REFUND_CONTEXT.search(text):
        return human("refund_approval_unverified", "The approved-refund timing FAQ does not cover an unapproved or unverified refund request.")
    second_requests = list(SECOND_REQUEST.finditer(text))
    if second_requests and not (
        len(second_requests) == 1
        and reply_type == "carrier_delay"
        and SUPPORTED_CARRIER_FOLLOWUP.search(text)
        and second_requests[0].group().strip().startswith("and what")
    ):
        return human("multi_intent_uncovered", "A second request is not covered by the selected FAQ reply.")
    replies = knowledge.get("replies", {})
    body = replies.get(reply_type) if isinstance(replies, dict) else None
    if not isinstance(body, str) or not body.strip() or len(body) > 1200:
        return human("faq_text_unavailable", "Approved reply text is unavailable.")
    entries = knowledge.get("entries")
    entry = entries.get(reply_type, {}) if isinstance(entries, dict) else {}
    required_status = "approved" if knowledge.get("status") == "approved" else "simulation"
    if not isinstance(entry, dict) or entry.get("review_status") != required_status:
        return human("faq_provenance_unavailable", "The knowledge entry has no valid review status.")
    if (entry.get("scope") != "general_information"
            or not isinstance(entry.get("source"), str)
            or not entry["source"].strip()):
        return human("faq_provenance_unavailable", "The knowledge entry has no general-information source.")
    return ReplyDecision(
        "informational", reply_type, body, knowledge.get("version"),
        "supported_faq", (reply_type,),
    )

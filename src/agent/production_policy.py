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
APPROVAL_POLICY_VERSION = "informational_only_v4"
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
    findings: tuple[tuple[str, str], ...] = ()
    required_evidence: tuple[str, ...] = ()


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


def _candidate_reply(ticket_text: str, *, knowledge: dict) -> ReplyDecision:
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


REQUIREMENTS = {
    "customer_facts_unverified": ("authoritative customer-specific record", "verified requester-to-record identity", "fresh conflict-free source"),
    "billing_data_unavailable": ("authoritative billing ledger", "verified requester identity", "human billing review"),
    "safety_incident": ("human safety review",),
    "manager_requested": ("human manager handoff",),
    "policy_exception": ("authorized human policy decision",),
    "business_action_unavailable": ("authorized action capability", "human action review"),
}


def decide_public_reply(ticket_text: str, *, knowledge: dict) -> ReplyDecision:
    """Shared fail-closed assessment; collect independent blockers without granting authority."""
    from dataclasses import replace
    candidate = _candidate_reply(ticket_text, knowledge=knowledge)
    findings = []
    text = ticket_text.casefold()
    checks = (
        (SAFETY_PATTERN, "safety_incident", "A safety incident requires human assessment."),
        (MANAGER_PATTERN, "manager_requested", "The requested manager handoff remains unresolved."),
        (POLICY_EXCEPTION_PATTERN, "policy_exception", "A policy exception requires an authorized human decision."),
        (BILLING_DISPUTE_PATTERN, "billing_data_unavailable", "No authoritative billing ledger is available."),
        (HIGH_STAKES, "high_stakes_or_sensitive", "High-stakes concerns require human review."),
        (SENSITIVE_REQUEST, "high_stakes_or_sensitive", "Sensitive credentials must not be requested or exposed."),
        (UNSUPPORTED_ACTION, "business_action_unavailable", "The requested action cannot be performed by this agent."),
    )
    for pattern, code, reason in checks:
        if pattern.search(text) and not any(item[0] == code for item in findings):
            findings.append((code, reason))
    if re.search(r"\b(?:ord-\d+|my (?:order|package|parcel|shipment|address|payment|card))\b", text):
        findings.append(("customer_facts_unverified", "Customer-specific facts lack authoritative source and identity verification."))
    if candidate.kind == "informational" and ticket_text.count("?") > 1:
        questions = [part.strip() for part in ticket_text.split("?") if part.strip()]
        if any(_candidate_reply(part, knowledge=knowledge).kind != "informational"
               or _candidate_reply(part, knowledge=knowledge).evidence_ids != candidate.evidence_ids
               for part in questions):
            findings.append(("multi_intent_uncovered", "Every separate question must be covered by the same approved reply."))
    if candidate.kind != "informational" and not any(code == candidate.reason_code for code, _ in findings):
        findings.append((candidate.reason_code, candidate.reason))
    if findings:
        required = tuple(dict.fromkeys(requirement for code, _ in findings
                                      for requirement in REQUIREMENTS.get(code, ("human request assessment",))))
        # Preserve existing primary reasons for compatibility; all findings are exposed.
        primary = candidate if candidate.kind == "human" else ReplyDecision(
            "human", findings[0][1], reason_code=findings[0][0])
        return replace(primary, findings=tuple(findings), required_evidence=required)
    return replace(candidate, required_evidence=("versioned FAQ entry", "exact approved reply text"))


def assess_reply_evidence(approval: ReplyDecision, *, review: dict, evidence: list[dict]) -> ReplyDecision:
    """Model coverage is necessary but cannot grant document authority."""
    from dataclasses import replace
    if approval.kind != "informational":
        return approval
    code, reason = "", ""
    if review.get("sufficient") is not True:
        code, reason = "rag_coverage_missing", "Retrieved guidance does not cover the entire request."
    else:
        selected = set(review.get("evidence_ids", []))
        body = " ".join((approval.body or "").split())
        matches = [item for item in evidence if item.get("chunk_id") in selected
                   and item.get("knowledge_id") in approval.evidence_ids
                   and item.get("review_status") == "simulation"
                   and item.get("approval_scope") == "automatic_reply_simulation"
                   and item.get("knowledge_version") == approval.knowledge_version
                   and isinstance(item.get("source"), str) and item["source"].strip()
                   and body and body in " ".join(item.get("text", "").split())]
        if not matches:
            code, reason = "rag_approval_evidence_missing", "No retrieved simulation-approved PDF contains the exact versioned reply."
    required = approval.required_evidence + ("retrieved hash-pinned simulation reply", "complete question coverage")
    if code:
        return replace(approval, kind="human", body=None, reason=reason, reason_code=code,
                       findings=((code, reason),), required_evidence=required)
    return replace(approval, required_evidence=required)


def validate_outgoing_reply(decision: ReplyDecision, body: str) -> bool:
    """Final exact-content check; a supervisor verdict cannot bypass the decision."""
    return (decision.kind == "informational" and not decision.findings
            and bool(decision.evidence_ids) and bool(decision.knowledge_version)
            and bool(decision.body) and body == decision.body
            and decision.policy_version == APPROVAL_POLICY_VERSION)

"""Shared risk patterns and the historical fixture-backed graph safety gate.

The current graph and controlled worker authorize informational replies through
production_policy.decide_public_reply. The gate below remains only for the
historical TASK-25/TASK-28 regression data; do not use it to authorize sends.
"""

from __future__ import annotations

import re
from typing import Any


ORDER_ID_PATTERN = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
BILLING_DISPUTE_PATTERN = re.compile(
    r"\b(duplicate charge|two (?:completed )?charges|charged twice|"
    r"unrecognized charge|unknown charge|charge after (?:i )?cancel|"
    r"billed after (?:i )?cancel|billing dispute|dispute(?:d)? (?:the )?(?:charge|tax|invoice)|"
    r"tax (?:on|charge)|partial refund|missing refund|refund (?:is )?(?:missing|partial|never arrived))\b|"
    r"\bcharge\b.{0,60}\b(?:don't recognize|do not recognize|cannot recognize|can't recognize|unauthorized|without permission)\b",
    re.IGNORECASE,
)
SAFETY_PATTERN = re.compile(
    r"\b(injur(?:y|ed)|burn(?:ed|ing)?|spark(?:s|ed|ing)?|electric shock|"
    r"caught fire|smok(?:e|es|ed|ing)|overheat(?:s|ed|ing)?|"
    r"dangerous|unsafe|hazard(?:ous)?|safety (?:issue|incident|review)|"
    r"hurt my child|child.{0,30}(?:hurt|burn|injur))\b",
    re.IGNORECASE,
)
MANAGER_PATTERN = re.compile(
    r"\b(manager|supervisor|human agent|real person|speak to a person|"
    r"escalate this|contact me immediately)\b",
    re.IGNORECASE,
)
POLICY_EXCEPTION_PATTERN = re.compile(
    r"\b(exception|warranty|outside.{0,30}(?:window|policy)|"
    r"window.{0,30}passed.{0,50}(?:but|however)|only noticed.{0,50}(?:today|later)|"
    r"review.{0,30}exception)\b",
    re.IGNORECASE,
)
AMBIGUITY_PATTERN = re.compile(
    r"\b(not sure|maybe.{0,30}(?:return|exchange|refund)|"
    r"don't know which|do not know which|can't decide|cannot decide|"
    r"it (?:still )?doesn't work|it does not work|something is wrong)\b",
    re.IGNORECASE,
)
ORDER_INTENT_PATTERN = re.compile(
    r"\b(where.{0,20}(?:order|package|shipment)|status of (?:my )?(?:order|package|shipment)|"
    r"track my|my package|my shipment|has not arrived|hasn't arrived|never arrived)\b",
    re.IGNORECASE,
)
GENERAL_GUIDANCE_PATTERN = re.compile(
    r"\b(how (?:can|do) i|where (?:can|do) i|what (?:should|do)|"
    r"how long|is (?:it|that) normal|usual|typically|when (?:does|will))\b",
    re.IGNORECASE,
)
CARRIER_SCAN_STALL_PATTERN = re.compile(
    r"\b(?:carrier\s+(?:tracking|scans?)|tracking(?:\s+(?:status|updates?))?)\b"
    r".{0,90}\b(?:hasn't changed|has not changed|hasn't updated|has not updated|"
    r"haven't changed|have not changed|haven't updated|have not updated|"
    r"isn't updating|is not updating|stopped updating|unchanged|paused|no updates?)\b",
    re.IGNORECASE,
)
SPECIFIC_SHIPMENT_REQUEST_PATTERN = re.compile(
    r"\b(?:where is|where's|check|look up|find|tell me|show me)\b"
    r".{0,45}\b(?:my|the)?\s*(?:order|package|shipment|tracking|status)\b|"
    r"\bwhen (?:will|does) (?:my|the) (?:order|package|shipment) arrive\b",
    re.IGNORECASE,
)
BUSINESS_ACTION_PATTERN = re.compile(
    r"\b(?:please |can you |i want you to |i need you to )?"
    r"(?:refund|cancel|replace|exchange|change my|update my|approve|issue)\b",
    re.IGNORECASE,
)
ACTION_REQUEST_PATTERN = re.compile(
    r"\b(?:please|can you|could you|i need you to|i want you to)\s+"
    r"(?:refund|cancel|replace|exchange|change|update|approve|issue)\b|"
    r"\b(?:change|update|edit|correct)\s+(?:my|the)\s+"
    r"(?:address|account|contact details|payment details)\b",
    re.IGNORECASE,
)
DELIVERY_NONRECEIPT_PATTERN = re.compile(
    r"\b(?:nobody|no one|none of us)\b.{0,50}\b(?:received|got|found)\b|"
    r"\b(?:didn't|did not|haven't|have not|never)\s+"
    r"(?:receive|received|get|got|arrive|arrived|show up)\b|"
    r"\b(?:package|parcel|order|item|delivery)\b.{0,25}\b(?:missing|not here|never arrived)\b",
    re.IGNORECASE,
)
UNSUPPORTED_SERVICE_PATTERN = re.compile(
    r"\b(?:overnight|same.day|international|guaranteed|"
    r"shipping (?:cost|price|rate)s?|delivery (?:cost|price|rate)s?)\b",
    re.IGNORECASE,
)
_GENERAL_FAQ_INTENTS = {
    "payment-methods": re.compile(
        r"\b(?:payment methods?|ways to pay|pay at checkout|which cards?)\b", re.I
    ),
    "shipping-status": re.compile(
        r"\b(?:tracking link|track (?:my|a|the) (?:shipment|package|order)|"
        r"find (?:the |my )?tracking)\b", re.I
    ),
    "refund-timing": re.compile(
        r"\brefund\b.{0,120}\b(?:how long|when|usually|business days|appear|posted|credited)\b",
        re.I,
    ),
    "return-window": re.compile(
        r"\breturn\b.{0,100}\b(?:window|within|how many days|how long|when|eligible)\b",
        re.I,
    ),
    "damaged-item": re.compile(
        r"\b(?:damage|damaged|broken|defective)\b.{0,100}\b(?:report|what should|how can|what do)\b",
        re.I,
    ),
}

_ORDER_DEPENDENT_CATEGORIES = {
    "order status",
    "return request",
    "damaged item",
}


def decide_send_safety(
    *,
    ticket_text: str,
    category: str | None,
    order_id: str | None,
    tool_results: dict[str, Any],
) -> dict[str, Any]:
    """Return a stable safety disposition, reasons, and evidence requirements."""
    findings: list[dict[str, str]] = []

    def block(code: str, reason: str, action: str = "human_review") -> None:
        if not any(item["code"] == code for item in findings):
            findings.append({"code": code, "reason": reason, "recommended_action": action})

    lowered_category = (category or "").strip().casefold()
    order_result = tool_results.get("order_lookup", {})
    policy_result = tool_results.get("policy_checker", {})
    faq_result = tool_results.get("faq_search", {})

    if lowered_category == "billing dispute" or BILLING_DISPUTE_PATTERN.search(ticket_text):
        block(
            "billing_unverified",
            "Billing records are unavailable, so the charge or refund cannot be verified.",
        )

    if SAFETY_PATTERN.search(ticket_text):
        block(
            "customer_safety_issue",
            "The ticket reports a possible injury or product-safety issue requiring human review.",
        )

    if MANAGER_PATTERN.search(ticket_text):
        block(
            "human_requested",
            "The customer explicitly requests a manager or human intervention.",
        )

    if POLICY_EXCEPTION_PATTERN.search(ticket_text):
        block(
            "policy_exception_requested",
            "The customer requests warranty, exception, or judgment beyond the available policy result.",
        )

    if AMBIGUITY_PATTERN.search(ticket_text):
        block(
            "clarification_required",
            "The customer's intent or the issue details are ambiguous; ask a focused clarification question.",
            action="request_clarification",
        )

    if ACTION_REQUEST_PATTERN.search(ticket_text):
        block(
            "business_action_unavailable",
            "The customer requests an account or order action this agent cannot perform; a person must handle it.",
        )

    explicit_order_ids = {value.upper() for value in ORDER_ID_PATTERN.findall(ticket_text)}
    # A question about general tracking or refund guidance does not become an
    # order lookup merely because it mentions a package or an old approval.
    general_question = (
        lowered_category == "general question"
        and bool(GENERAL_GUIDANCE_PATTERN.search(ticket_text))
        and not bool(BUSINESS_ACTION_PATTERN.search(ticket_text))
        and not explicit_order_ids
    )
    faq_data = faq_result.get("data") if isinstance(faq_result, dict) else None
    faq_matches = (
        faq_data.get("matches", [])
        if faq_result.get("ok") is True and isinstance(faq_data, dict)
        else []
    )
    has_shipping_delay_faq = isinstance(faq_matches, list) and any(
        isinstance(match, dict) and match.get("id") == "shipping-delay"
        for match in faq_matches
    )
    faq_ids: set[str] = set()
    if isinstance(faq_matches, list):
        for match in faq_matches:
            if isinstance(match, dict) and isinstance(match.get("id"), str):
                faq_ids.add(match["id"])
    supported_general_faq = (
        has_shipping_delay_faq and bool(CARRIER_SCAN_STALL_PATTERN.search(ticket_text))
    ) or any(
        faq_id in faq_ids and intent.search(ticket_text)
        for faq_id, intent in _GENERAL_FAQ_INTENTS.items()
    )
    if lowered_category == "general question" and (
        not supported_general_faq or UNSUPPORTED_SERVICE_PATTERN.search(ticket_text)
    ):
        block(
            "unsupported_general_request",
            "No relevant supported FAQ covers the customer's complete question; a person must answer it.",
        )
    carrier_scan_guidance = (
        lowered_category in {"general question", "order status"}
        and bool(CARRIER_SCAN_STALL_PATTERN.search(ticket_text))
        and bool(GENERAL_GUIDANCE_PATTERN.search(ticket_text))
        and not bool(SPECIFIC_SHIPMENT_REQUEST_PATTERN.search(ticket_text))
        and not bool(BUSINESS_ACTION_PATTERN.search(ticket_text))
        and not explicit_order_ids
        and has_shipping_delay_faq
    )
    informational = general_question or carrier_scan_guidance
    order_dependent = not informational and (
        lowered_category in _ORDER_DEPENDENT_CATEGORIES
        or bool(ORDER_INTENT_PATTERN.search(ticket_text))
    )
    if order_dependent and not explicit_order_ids:
        block(
            "order_id_required",
            "No explicit order ID is present; request the order ID before making order-specific claims.",
            action="request_clarification",
        )
    elif order_dependent and order_id and order_id.upper() not in explicit_order_ids:
        block(
            "order_id_not_in_ticket",
            "The extracted order ID is not explicitly present in the current ticket.",
        )
    elif order_dependent and explicit_order_ids and order_result.get("ok") is not True:
        error = order_result.get("error")
        error_type = error.get("type") if isinstance(error, dict) else None
        code = "order_not_found" if error_type == "ToolNotFoundError" else "order_data_unavailable"
        block(
            code,
            "The current order source did not return a verified record for the requested order.",
        )

    order_data = order_result.get("data") if isinstance(order_result, dict) else None
    if (
        order_result.get("ok") is True
        and isinstance(order_data, dict)
        and str(order_data.get("status", "")).casefold() == "delivered"
        and DELIVERY_NONRECEIPT_PATTERN.search(ticket_text)
    ):
        block(
            "delivery_dispute_requires_investigation",
            "The order is marked delivered, but the customer reports nonreceipt; the available record cannot resolve that conflict.",
        )

    if lowered_category in {"return request", "damaged item"} and policy_result.get("ok") is not True:
        block(
            "policy_data_unavailable",
            "The policy source did not return a verified eligibility result.",
        )

    status = "send_allowed" if not findings else "blocked"
    required_evidence = ["supervisor PASS", "all relevant source records verified"]
    return {
        "status": status,
        "send_allowed": status == "send_allowed",
        "findings": findings,
        "required_evidence": required_evidence,
    }

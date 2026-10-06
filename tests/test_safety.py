import pytest

from src.agent.safety import decide_send_safety


def _results(*, order_ok=True, policy_ok=True, order_error="ToolNotFoundError"):
    return {
        "order_lookup": (
            {"ok": True, "data": {"order_id": "ORD-1001", "status": "shipped"}}
            if order_ok
            else {
                "ok": False,
                "availability": "unavailable",
                "error": {"type": order_error, "source": "order_lookup"},
            }
        ),
        "policy_checker": (
            {"ok": True, "data": {"eligible": True, "policy_window_days": 30}}
            if policy_ok
            else {
                "ok": False,
                "availability": "unavailable",
                "error": {"type": "ToolExecutionError", "source": "policy_checker"},
            }
        ),
        "faq_search": {"ok": True, "data": {"matches": []}},
    }


def _codes(decision):
    return {finding["code"] for finding in decision["findings"]}


@pytest.mark.parametrize(
    ("category", "text", "code"),
    [
        ("billing dispute", "There is a duplicate charge on my account.", "billing_unverified"),
        ("order status", "Get me a manager about ORD-1001.", "human_requested"),
        ("damaged item", "This lamp sparked and burned my child's finger.", "customer_safety_issue"),
        (
            "return request",
            "The normal return window passed, but this is a warranty issue. Review an exception for ORD-1001.",
            "policy_exception_requested",
        ),
        (
            "return request",
            "I might return or exchange ORD-1001, and I don't know which to choose.",
            "clarification_required",
        ),
        ("order status", "Where is my order?", "order_id_required"),
    ],
)
def test_deterministic_rules_block_send(category, text, code):
    order_id = "ORD-1001" if "ORD-1001" in text else None
    decision = decide_send_safety(
        ticket_text=text,
        category=category,
        order_id=order_id,
        tool_results=_results(),
    )

    assert decision["send_allowed"] is False
    assert code in _codes(decision)


def test_unknown_order_is_typed_and_blocks_send():
    decision = decide_send_safety(
        ticket_text="Where is ORD-9999?",
        category="order status",
        order_id="ORD-9999",
        tool_results=_results(order_ok=False),
    )

    assert decision["send_allowed"] is False
    assert "order_not_found" in _codes(decision)


def test_unavailable_policy_source_blocks_policy_decision():
    decision = decide_send_safety(
        ticket_text="Can I return ORD-1001?",
        category="return request",
        order_id="ORD-1001",
        tool_results=_results(policy_ok=False),
    )

    assert decision["send_allowed"] is False
    assert "policy_data_unavailable" in _codes(decision)


@pytest.mark.parametrize(
    ("category", "text", "order_id"),
    [
        ("order status", "Where is ORD-1001?", "ORD-1001"),
        ("return request", "I no longer need ORD-1001; it was delivered 45 days ago.", "ORD-1001"),
        ("general question", "How do I find the tracking link after an order ships?", None),
    ],
)
def test_relevant_facts_and_routine_questions_can_pass_deterministic_gate(
    category, text, order_id
):
    results = _results()
    if category == "general question":
        results["faq_search"]["data"]["matches"] = [{"id": "shipping-status"}]
    decision = decide_send_safety(
        ticket_text=text,
        category=category,
        order_id=order_id,
        tool_results=results,
    )

    assert decision["send_allowed"] is True
    assert decision["findings"] == []


@pytest.mark.parametrize(
    "text",
    [
        "My carrier tracking hasn't changed since yesterday. Is that normal, and what should I do if the expected delivery date passes?",
        "Carrier scans have not updated today. Is that normal and what should I do?",
    ],
)
def test_carrier_scan_guidance_uses_faq_even_when_classified_order_status(text):
    results = _results(order_ok=False, policy_ok=False)
    results["faq_search"]["data"]["matches"] = [{"id": "shipping-delay"}]
    decision = decide_send_safety(
        ticket_text=text,
        category="order status",
        order_id=None,
        tool_results=results,
    )
    assert decision["send_allowed"] is True
    assert decision["findings"] == []


@pytest.mark.parametrize(
    "text,faq_ok",
    [
        ("My carrier tracking hasn't changed. Is that normal? Please check my package status.", True),
        ("My carrier tracking hasn't changed. Is that normal?", False),
        ("My carrier tracking hasn't changed. Is that normal for ORD-1001?", True),
    ],
)
def test_carrier_scan_exception_cannot_bypass_order_or_faq_evidence(text, faq_ok):
    results = _results(order_ok=False, policy_ok=False)
    results["faq_search"]["data"]["matches"] = (
        [{"id": "shipping-delay"}] if faq_ok else []
    )
    decision = decide_send_safety(
        ticket_text=text,
        category="order status",
        order_id=None,
        tool_results=results,
    )
    assert decision["send_allowed"] is False
    assert "order_id_required" in _codes(decision) or "order_not_found" in _codes(decision)


@pytest.mark.parametrize("text", [
    "ORD-1003 shows delivered, but nobody at my address received the lamp. Please investigate.",
    "ORD-1003 is marked delivered, but I never got the desk lamp. Where did it go?",
])
def test_delivered_but_not_received_requires_investigation(text):
    results = _results()
    results["order_lookup"]["data"].update(order_id="ORD-1003", status="delivered")
    decision = decide_send_safety(
        ticket_text=text, category="order status", order_id="ORD-1003", tool_results=results
    )
    assert decision["send_allowed"] is False
    assert "delivery_dispute_requires_investigation" in _codes(decision)


def test_routine_delivered_status_stays_eligible():
    results = _results()
    results["order_lookup"]["data"].update(order_id="ORD-1003", status="delivered")
    decision = decide_send_safety(
        ticket_text="What is the current status of ORD-1003?",
        category="order status", order_id="ORD-1003", tool_results=results,
    )
    assert decision["send_allowed"] is True


@pytest.mark.parametrize("description", [
    "started smoking", "was sparking", "overheated", "needs a safety review",
])
def test_product_hazards_require_human_review(description):
    decision = decide_send_safety(
        ticket_text=f"The speaker in ORD-1006 {description}. Please help.",
        category="damaged item", order_id="ORD-1006", tool_results=_results(),
    )
    assert "customer_safety_issue" in _codes(decision)
    assert decision["send_allowed"] is False


def test_irrelevant_faq_does_not_answer_service_price():
    results = _results(order_ok=False, policy_ok=False)
    results["faq_search"]["data"]["matches"] = [{"id": "shipping-status"}]
    decision = decide_send_safety(
        ticket_text="Do you offer guaranteed overnight delivery to Canada, and what does it cost?",
        category="general question", order_id=None, tool_results=results,
    )
    assert "unsupported_general_request" in _codes(decision)
    assert decision["send_allowed"] is False


def test_address_change_request_is_not_a_faq_answer():
    results = _results(order_ok=False, policy_ok=False)
    results["faq_search"]["data"]["matches"] = [{"id": "payment-methods"}]
    decision = decide_send_safety(
        ticket_text="Please change my address, but I cannot remember which order it belongs to.",
        category="general question", order_id=None, tool_results=results,
    )
    assert "business_action_unavailable" in _codes(decision)
    assert decision["send_allowed"] is False


@pytest.mark.parametrize("text,faq_id", [
    ("Which payment methods can I use at checkout?", "payment-methods"),
    ("How do I find the tracking link after shipping?", "shipping-status"),
    ("After my refund is approved, how long does it usually take to appear?", "refund-timing"),
])
def test_relevant_general_faq_stays_eligible(text, faq_id):
    results = _results(order_ok=False, policy_ok=False)
    results["faq_search"]["data"]["matches"] = [{"id": faq_id}]
    decision = decide_send_safety(
        ticket_text=text, category="general question", order_id=None, tool_results=results,
    )
    assert decision["send_allowed"] is True


def test_standard_return_question_is_not_an_action_request():
    decision = decide_send_safety(
        ticket_text="Can I return ORD-1002 under the standard policy, or get a refund?",
        category="return request", order_id="ORD-1002", tool_results=_results(),
    )
    assert "business_action_unavailable" not in _codes(decision)

from src.agent.triage import derive_triage


def test_explicit_urgent_and_safety_signals_override_low_model_urgency():
    for text in (
        "This is urgent; my package is needed today.",
        "The device sparked and burned my hand.",
        "Please connect me with a manager immediately.",
    ):
        triage = derive_triage(
            text,
            model_urgency="low",
            classification_basis="llm_classification",
            category_basis="llm_classification",
        )
        assert triage["urgency"] == "high"
        assert triage["priority"] == "P1"
        assert triage["priority_rank"] == 1
        assert triage["urgency_basis"] == "explicit_high_priority_signal"


def test_medium_impact_wording_raises_low_model_urgency_to_p2():
    triage = derive_triage(
        "This is the second time I have reported the damaged item.",
        model_urgency="low",
        classification_basis="llm_classification",
        category_basis="llm_classification",
    )

    assert triage["urgency"] == "medium"
    assert triage["priority"] == "P2"
    assert triage["priority_rank"] == 2


def test_low_classifier_urgency_maps_to_routine_priority():
    triage = derive_triage(
        "Which payment methods can I use at checkout?",
        model_urgency="low",
        classification_basis="approved_faq_intent",
        category_basis="approved_faq_intent",
    )

    assert triage == {
        "urgency": "low",
        "priority": "P3",
        "priority_rank": 3,
        "classification_basis": "approved_faq_intent",
        "category_basis": "approved_faq_intent",
        "urgency_basis": "classifier_urgency",
    }


def test_clear_transaction_return_and_order_intents_correct_model_category():
    cases = [
        (
            "The blender in ORD-1004 stopped working two days after it was delivered, "
            "although that was 45 days ago. The normal return window has passed, but "
            "I think this is a warranty issue. Can someone review an exception?",
            "damaged item",
            "return request",
            "explicit_return_intent",
        ),
        (
            "I bought ORD-1004 45 days ago. Does the normal return window still cover it?",
            "general question",
            "return request",
            "explicit_return_intent",
        ),
        (
            "ORD-1001 is on its way. Can I submit a normal return before it arrives?",
            "general question",
            "return request",
            "explicit_return_intent",
        ),
        (
            "Payment left my account yesterday, but I did not receive an order "
            "confirmation. Can you find the transaction and tell me whether my purchase went through?",
            "order status",
            "billing dispute",
            "explicit_billing_intent",
        ),
    ]

    from src.agent.triage import reconcile_category

    for ticket_text, model_category, expected_category, expected_basis in cases:
        assert reconcile_category(ticket_text, model_category) == (
            expected_category,
            expected_basis,
        )


def test_bare_today_mention_does_not_promote_low_ticket_to_p1():
    from src.agent.triage import derive_triage

    triage = derive_triage(
        "The tracking page has not updated today.",
        model_urgency="low",
        classification_basis="llm_classification",
        category_basis="llm_classification",
    )

    assert triage["urgency"] == "low"
    assert triage["priority"] == "P3"
    assert triage["urgency_basis"] == "classifier_urgency"


def test_vague_malfunction_does_not_override_category_to_damaged_item():
    from src.agent.triage import reconcile_category

    assert reconcile_category(
        "It still doesn't work and I need someone to fix this.",
        "general question",
    ) == ("general question", "llm_classification")


def test_explicit_defect_overrides_wrong_model_category():
    from src.agent.triage import reconcile_category

    assert reconcile_category(
        "My desk lamp has a defective switch.",
        "general question",
    ) == ("damaged item", "explicit_damage_intent")


def test_specific_product_malfunction_overrides_wrong_model_category():
    from src.agent.triage import reconcile_category

    assert reconcile_category(
        "The blender stopped working after I unpacked it.",
        "general question",
    ) == ("damaged item", "explicit_damage_intent")

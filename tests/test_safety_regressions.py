from src.eval.run_safety_regressions import evaluate_safety_cases, load_safety_cases


def test_expanded_safety_regression_set_has_expected_evidence_and_criteria():
    cases = load_safety_cases()

    assert len(cases) == 31
    assert all(case["required_evidence"] for case in cases)
    assert all(case["acceptable_response"] for case in cases)
    assert all(case["acceptable_terminal_outcome"] in {"sent", "escalated"} for case in cases)
    assert {case["category"] for case in cases} >= {
        "billing dispute", "order status", "damaged item", "return request", "general question"
    }


def test_deterministic_safety_regression_suite_matches_labels():
    report = evaluate_safety_cases(load_safety_cases())

    assert report["attempted"] == 31
    assert report["matched"] == 31
    assert report["false_sends"] == 0
    assert report["missed_escalations"] == 0
    assert report["false_escalations"] == 0
    assert all(
        result["matches"] for result in report["results"]
    )

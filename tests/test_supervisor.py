"""Unit tests for structured supervisor checklist reviews."""

import json

from src.agent.supervisor import SUPERVISOR_CHECKLIST, parse_supervisor_review


def test_review_verdict_is_derived_from_checklist_results():
    payload = {
        "checks": [
            {
                "id": check["id"],
                "passed": check["id"] != "no_unsupported_claims",
                "reason": "Supported." if check["id"] != "no_unsupported_claims" else "Unsupported refund claim.",
            }
            for check in SUPERVISOR_CHECKLIST
        ]
    }

    status, reason = parse_supervisor_review(json.dumps(payload))

    assert status == "FAIL"
    assert reason["failed_checks"] == ["no_unsupported_claims"]


def test_invalid_review_fails_closed_with_structured_reason():
    status, reason = parse_supervisor_review('{"checks":[]}')

    assert status == "FAIL"
    assert reason["failed_checks"] == ["supervisor_output_valid"]
    assert reason["error"]["code"] == "invalid_supervisor_output"

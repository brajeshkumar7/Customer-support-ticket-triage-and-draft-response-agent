"""Structured checklist and result validation for the graph's supervisor node."""

import json
from typing import Any

SUPERVISOR_CHECKLIST = [
    {
        "id": "factual_claims_grounded",
        "check": (
            "Every factual claim in the draft is backed by a successful tool result "
            "actually present in the current state."
        ),
    },
    {
        "id": "no_unsupported_claims",
        "check": (
            "The draft does not claim order, policy, refund, delivery, or account "
            "facts that no successful tool returned."
        ),
    },
    {
        "id": "urgency_appropriate_tone",
        "check": (
            "The tone matches ticket urgency: high urgency is empathetic and prompt "
            "without minimizing the issue; medium urgency is attentive and clear; "
            "low urgency is calm and courteous."
        ),
    },
]


def _invalid_review(message: str) -> tuple[str, dict[str, Any]]:
    return "FAIL", {
        "summary": "Supervisor could not validate its structured review.",
        "checks": [],
        "failed_checks": ["supervisor_output_valid"],
        "error": {"code": "invalid_supervisor_output", "message": message},
    }


def parse_supervisor_review(content: str) -> tuple[str, dict[str, Any]]:
    """Validate checklist results and derive PASS/FAIL instead of trusting a verdict."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        return _invalid_review(f"Expected JSON object: {error.msg}.")

    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
        return _invalid_review('Expected an object with a "checks" list.')

    expected_ids = [check["id"] for check in SUPERVISOR_CHECKLIST]
    result_by_id: dict[str, dict[str, Any]] = {}
    for result in payload["checks"]:
        if not isinstance(result, dict):
            return _invalid_review("Each check result must be an object.")
        check_id = result.get("id")
        passed = result.get("passed")
        reason = result.get("reason")
        if check_id not in expected_ids:
            return _invalid_review(f"Unknown check ID: {check_id!r}.")
        if check_id in result_by_id:
            return _invalid_review(f"Duplicate check ID: {check_id!r}.")
        if not isinstance(passed, bool) or not isinstance(reason, str) or not reason.strip():
            return _invalid_review(
                f"Check {check_id!r} must include a boolean passed value and a reason."
            )
        result_by_id[check_id] = {
            "id": check_id,
            "passed": passed,
            "reason": reason.strip(),
        }

    missing_ids = [check_id for check_id in expected_ids if check_id not in result_by_id]
    if missing_ids:
        return _invalid_review("Missing check results: " + ", ".join(missing_ids) + ".")

    checks = [result_by_id[check_id] for check_id in expected_ids]
    failed_checks = [check["id"] for check in checks if not check["passed"]]
    status = "FAIL" if failed_checks else "PASS"
    summary = (
        "All supervisor checklist checks passed."
        if status == "PASS"
        else "One or more supervisor checklist checks failed."
    )
    return status, {
        "summary": summary,
        "checks": checks,
        "failed_checks": failed_checks,
    }

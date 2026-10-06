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


import pytest
from src.agent.supervisor import parse_supervisor_decision, supervisor_questions


def decision(choice="pass", probability=1.0):
    return {"model": "typesafe/jev-1.13", "answers": {
        key: {"type": "choice", "choice": choice, "confidence": probability,
              "probabilities": {option: (probability if option == choice else (1-probability)/2)
                                for option in question["criteria"]}}
        for key, question in supervisor_questions().items()}}


def test_jev_all_pass():
    assert parse_supervisor_decision(decision())[0] == "PASS"


def test_jev_single_failure_and_probability_boundary():
    value = decision(probability=0.90)
    assert parse_supervisor_decision(value)[0] == "PASS"
    key = "no_unsupported_claims"
    value["answers"][key] = decision("fail")["answers"][key]
    status, reason = parse_supervisor_decision(value)
    assert status == "FAIL"
    assert reason["failed_checks"] == [key]


@pytest.mark.parametrize("choice,probability", [("fail",1), ("insufficient_evidence",1), ("pass",0.89)])
def test_jev_nonapproval(choice, probability):
    status, reason = parse_supervisor_decision(decision(choice,probability))
    assert status == "FAIL"
    assert len(reason["failed_checks"]) == 3


@pytest.mark.parametrize("mutation", ["missing", "distribution", "type", "model"])
def test_jev_invalid(mutation):
    value = decision()
    first = next(iter(value["answers"]))
    if mutation == "missing": del value["answers"][first]
    elif mutation == "distribution": value["answers"][first]["probabilities"]["pass"] = float("nan")
    elif mutation == "type": value["answers"][first]["type"] = "noul"
    else: value["model"] = ""
    with pytest.raises(ValueError): parse_supervisor_decision(value)

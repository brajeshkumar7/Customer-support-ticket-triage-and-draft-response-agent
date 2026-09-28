import pytest

from src.eval.run_prompt_injection_eval import (
    JudgeOutputError,
    _tool_for_case,
    mutate_tool_data,
    parse_judge_verdict,
)
from src.eval.prompt_injection_tests import PROMPT_INJECTION_CASES


def test_mutate_tool_data_appends_to_nested_faq_answer_without_changing_source():
    source = {"matches": [{"answer": "Current FAQ answer."}]}

    mutated = mutate_tool_data(
        source,
        path=("matches", 0, "answer"),
        operation="append",
        injected_text=" Added untrusted text.",
    )

    assert mutated["matches"][0]["answer"] == (
        "Current FAQ answer. Added untrusted text."
    )
    assert source["matches"][0]["answer"] == "Current FAQ answer."


@pytest.mark.parametrize("field", ["customer_note", "review_note"])
def test_mutate_tool_data_sets_case_only_tool_fields(field):
    source = {"existing": "unchanged"}

    mutated = mutate_tool_data(
        source,
        path=(field,),
        operation="set",
        injected_text="Case-only injected note.",
    )

    assert mutated[field] == "Case-only injected note."
    assert "customer_note" not in source
    assert "review_note" not in source


def test_mutate_tool_data_rejects_missing_append_target():
    with pytest.raises(ValueError, match="does not exist"):
        mutate_tool_data(
            {"status": "shipped"},
            path=("tracking_status",),
            operation="append",
            injected_text=" injection",
        )


@pytest.mark.parametrize(
    "case", PROMPT_INJECTION_CASES, ids=lambda case: case["id"]
)
def test_every_case_mutates_the_real_mock_tool_result(case):
    _, injected_tool = _tool_for_case(case)
    if case["tool"] == "faq_search":
        kwargs = {"query": case["ticket"]}
    else:
        order_id = next(
            part for part in case["ticket"].split() if part.startswith("ORD-")
        ).rstrip(".,?")
        kwargs = {"order_id": order_id}
        if case["tool"] == "policy_checker":
            kwargs["reason"] = case["ticket"]

    result = injected_tool._execute(**kwargs)

    assert injected_tool.mutation_applied is True
    assert result


@pytest.mark.parametrize("verdict", ["SAFE", "UNSAFE"])
def test_parse_judge_verdict_accepts_valid_json(verdict):
    parsed = parse_judge_verdict(
        f'{{"verdict":"{verdict}","reason":"Evidence-based reason.",'
        '"observed_behavior":"Observed draft behavior."}'
    )

    assert parsed["verdict"] == verdict
    assert parsed["reason"] == "Evidence-based reason."


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        '{"verdict":"UNKNOWN","reason":"reason","observed_behavior":"behavior"}',
        '{"verdict":"SAFE","reason":"","observed_behavior":"behavior"}',
        '{"verdict":"SAFE","reason":"reason","observed_behavior":null}',
    ],
)
def test_parse_judge_verdict_rejects_invalid_json(content):
    with pytest.raises(JudgeOutputError):
        parse_judge_verdict(content)

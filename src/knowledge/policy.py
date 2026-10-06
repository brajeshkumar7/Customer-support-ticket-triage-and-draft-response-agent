"""Validated fictional business policy shared by tools and PDF authoring."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from src.tools.base import ToolUnavailableError

POLICY_PATH = Path(__file__).resolve().parents[2] / "data/policies/support_v1.json"

class PolicySourceError(ToolUnavailableError):
    def __init__(self, message: str):
        super().__init__("policy_checker", message)

def load_policy(path: Path | None = None) -> dict:
    try:
        raw = (path or POLICY_PATH).read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as error:
        raise PolicySourceError("Business policy source is unavailable or malformed.") from error
    if not isinstance(data, dict):
        raise PolicySourceError("Business policy must be an object.")
    if (data.get("policy_id") != "fictional_support" or data.get("version") != "v1"
            or data.get("review_status") != "simulation"
            or not isinstance(data.get("source"), str) or not data["source"].strip()
            or data.get("requires_delivered") is not True
            or data.get("mandatory_human_review") != ["safety_incident", "policy_exception"]):
        raise PolicySourceError("Unsupported business policy identity, review status or conditions.")
    rules = data.get("rules")
    if not isinstance(rules, dict) or set(rules) != {"returns", "damage"}:
        raise PolicySourceError("Business policy must define returns and damage rules.")
    for rule in rules.values():
        if (not isinstance(rule, dict) or set(rule) != {"window_days"}
                or type(rule["window_days"]) is not int or not 1 <= rule["window_days"] <= 365):
            raise PolicySourceError("Business policy reporting windows are invalid.")
    return {**data, "policy_sha256": hashlib.sha256(raw).hexdigest()}

def policy_configuration() -> dict:
    try:
        data = load_policy()
    except PolicySourceError:
        return {"available": False}
    return {"available": True, "policy_id": data["policy_id"],
            "policy_version": data["version"], "policy_sha256": data["policy_sha256"]}

def policy_text(policy: dict, rule_id: str) -> str:
    window = policy["rules"][rule_id]["window_days"]
    subject = "Return requests" if rule_id == "returns" else "Damage reports"
    return (f"{subject} are within the reporting window up to and including {window} days after delivery. "
            "The order must be delivered before eligibility can be evaluated. "
            "Window eligibility is not approval to issue a refund, replacement or return. "
            "Safety incidents and discretionary policy exceptions require human review regardless of the window. "
            "Order records are fictional fixtures; these rules are simulation reference only, not real merchant policy.")

def is_active_policy_chunk(item: dict, configuration: dict) -> bool:
    if item.get("knowledge_id") in {"returns", "damage"} and not item.get("policy_id"):
        return False
    if item.get("policy_id"):
        return (configuration.get("available") is True
                and all(item.get(key) == configuration.get(key) for key in
                        ("policy_id", "policy_version", "policy_sha256"))
                and item.get("review_status") == "simulation")
    return True

def policy_evidence_findings(result: dict, evidence: list[dict], *, use_rag: bool) -> list[tuple[str,str]]:
    if result.get("ok") is not True:
        return [("business_policy_unavailable", "The policy check could not obtain usable evidence.")]
    config = policy_configuration()
    data = result.get("data", {})
    if not config.get("available") or any(data.get(key) != config.get(key) for key in
                                           ("policy_id", "policy_version", "policy_sha256")):
        return [("business_policy_mismatch", "The policy result does not match the active source version and hash.")]
    ids = data.get("rule_ids")
    if not isinstance(ids, list) or len(ids) != 1 or any(rule not in {"returns", "damage"} for rule in ids):
        return [("business_policy_rules_invalid", "The policy result has invalid rule identifiers.")]
    if (type(data.get("eligible")) is not bool or type(data.get("requires_human_review")) is not bool
            or (data.get("policy_window_days") is not None and
                (type(data["policy_window_days"]) is not int or
                 data["policy_window_days"] != load_policy()["rules"][ids[0]]["window_days"]))):
        return [("business_policy_result_conflict", "Policy assessment fields conflict with the active rule.")]
    if data.get("requires_human_review") is True:
        findings = [("business_policy_human_review", "This policy assessment requires a human decision.")]
    else:
        findings = []
    if use_rag:
        chunks = [item for item in evidence if item.get("policy_id") == config["policy_id"]]
        if any(not is_active_policy_chunk(item, config) or not isinstance(item.get("rule_ids"), list)
               or any(rule not in {"returns", "damage"} for rule in item["rule_ids"]) for item in chunks):
            findings.append(("business_policy_evidence_mismatch", "Retrieved policy metadata conflicts with the active policy."))
        covered = {rule for item in chunks if is_active_policy_chunk(item, config)
                   and item.get("approval_scope") == "reference_only"
                   and isinstance(item.get("rule_ids"), list) for rule in item["rule_ids"]}
        if not set(ids).issubset(covered):
            findings.append(("business_policy_evidence_missing", "Matching retrieved policy rules are missing."))
    return findings

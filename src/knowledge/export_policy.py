"""CLI: python -m src.knowledge.export_policy; never overwrites immutable PDFs."""
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from src.knowledge.policy import load_policy, policy_text

ROOT = Path(__file__).resolve().parents[2]

def export_policy(folder: Path | None = None, policy_path: Path | None = None) -> dict:
    policy = load_policy(policy_path)
    folder = folder or ROOT / "knowledgebase"
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if not isinstance(manifest, dict):
        raise ValueError("PDF manifest must be an object.")
    records = []
    # Preflight both files before any creation; immutable versions cannot be replaced.
    for rule_id in policy["rules"]:
        name = f"policy_{policy['policy_id']}_{policy['version']}_{rule_id}.pdf"
        path = folder / name
        entry = manifest.get(name, {})
        if path.exists():
            if (entry.get("policy_id") != policy["policy_id"]
                    or entry.get("policy_version") != policy["version"]
                    or entry.get("review_status") != "simulation"
                    or entry.get("approval_scope") != "reference_only"
                    or entry.get("policy_sha256") != policy["policy_sha256"]
                    or entry.get("rule_ids") != [rule_id]
                    or entry.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
                raise ValueError("Existing policy PDF differs; create a new policy version instead.")
        elif name in manifest:
            raise ValueError("Manifest references a missing policy PDF; inspect before authoring.")
        records.append((rule_id, name, path))
    report = {"created": [], "skipped": []}
    styles = getSampleStyleSheet()
    for rule_id, name, path in records:
        if path.exists():
            report["skipped"].append(name)
            continue
        doc = SimpleDocTemplate(str(path), title=f"Simulation policy: {rule_id}", invariant=1)
        doc.build([Paragraph(f"{rule_id.title()} policy", styles["Title"]),
                   Paragraph("SIMULATION REFERENCE ONLY", styles["Heading2"]), Spacer(1, 14),
                   Paragraph(escape(policy_text(policy, rule_id)), styles["BodyText"]), Spacer(1, 14),
                   Paragraph(f"Policy: {policy['policy_id']}; version: {policy['version']}; rule: {rule_id}.", styles["Normal"])])
        manifest[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "knowledge_id": f"business_policy_{rule_id}", "knowledge_version": policy["version"],
                          "review_status": policy["review_status"], "approval_scope": "reference_only",
                          "source": policy["source"], "policy_id": policy["policy_id"],
                          "policy_version": policy["version"], "policy_sha256": policy["policy_sha256"],
                          "rule_ids": [rule_id]}
        report["created"].append(name)
    if report["created"]:
        pending = manifest_path.with_suffix(".pending")
        pending.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        pending.replace(manifest_path)
    return report

def main():
    try:
        print(json.dumps(export_policy(), indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Policy export failed: {error}") from error

if __name__ == "__main__":
    main()

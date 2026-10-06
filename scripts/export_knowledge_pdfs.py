"""Export the existing fictional merchant guidance as reproducible seed PDFs.

This is an explicit authoring command, not part of normal incremental ingestion.
It never upgrades review status or downloads third-party merchant policies.
"""
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[1]


def main():
    knowledge = json.loads((ROOT / "data/approved_knowledge/v1.json").read_text(encoding="utf-8"))
    folder = ROOT / "knowledgebase"
    folder.mkdir(exist_ok=True)
    styles = getSampleStyleSheet()
    manifest = {}
    documents = [(key, value, "general_information") for key, value in knowledge["replies"].items()]
    documents += [(key, value, "policy_reference") for key, value in knowledge["policy_reference"].items()]
    documents.append(("data_boundaries", "Order, shipment and billing records in this project are fixtures. They do not verify a real customer's purchase, delivery, charge or refund. Safety incidents, business actions, policy exceptions and manager requests require a human. Historical ticket summaries are not approval evidence.", "safety_reference"))
    for key, text, scope in documents:
        path = folder / f"{key}.pdf"
        doc = SimpleDocTemplate(str(path), title=key.replace("_", " ").title(), author="Fictional merchant simulation", invariant=1)
        story = [Paragraph(key.replace("_", " ").title(), styles["Title"]), Spacer(1, 16),
                 Paragraph("SIMULATION ONLY - fictional merchant guidance", styles["Heading2"]),
                 Paragraph("Version v1. Review status: simulation. Not approved for real customer automation.", styles["Normal"]), Spacer(1, 16),
                 Paragraph(escape(text), styles["BodyText"]), Spacer(1, 20),
                 Paragraph(f"Knowledge ID: {key}. Scope: {scope}. Source: repository local merchant example.", styles["Normal"])]
        def footer(canvas, document):
            canvas.setFillColor(colors.grey)
            canvas.drawString(72, 40, "Local support-agent knowledge | simulation only | page 1")
        doc.build(story, onFirstPage=footer)
        manifest[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "knowledge_id": key, "knowledge_version": knowledge["version"],
                               "review_status": "simulation", "source": "local fictional merchant guidance v1"}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(documents)} simulation PDFs to {folder}.")


if __name__ == "__main__":
    main()

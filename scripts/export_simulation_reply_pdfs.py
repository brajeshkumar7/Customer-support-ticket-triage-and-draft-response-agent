"""Export separate simulation reply PDFs; preserve all existing reference documents."""
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[1]

def main():
    knowledge = json.loads((ROOT / "data/approved_knowledge/v1.json").read_text(encoding="utf-8"))
    folder = ROOT / "knowledgebase"
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    styles = getSampleStyleSheet()
    for key, body in knowledge["replies"].items():
        filename = f"simulation_reply_v1_{key}.pdf"
        path = folder / filename
        if path.exists():
            raise ValueError(f"Immutable document already exists: {filename}")
        doc = SimpleDocTemplate(str(path), title=f"Simulation reply: {key}", invariant=1)
        doc.build([Paragraph(key.replace("_", " ").title(), styles["Title"]),
                   Paragraph("SIMULATION ONLY - exact local reply, version v1", styles["Heading2"]),
                   Spacer(1, 16), Paragraph(escape(body), styles["BodyText"]), Spacer(1, 16),
                   Paragraph("Approved for fictional informational simulations only. Does not verify customer records or authorize live delivery.", styles["Normal"])])
        manifest[filename] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "knowledge_id": key, "knowledge_version": "v1",
                              "review_status": "simulation", "source": "data/approved_knowledge/v1.json fictional reply collection",
                              "approval_scope": "automatic_reply_simulation", "reviewed_at": "2026-10-06"}
    manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")

if __name__ == "__main__":
    main()

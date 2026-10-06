"""CLI: python -m src.knowledge.ingest [--folder knowledgebase]."""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from src.knowledge.store import KnowledgeStore, ROOT


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Incrementally chunk PDFs and build dense + sparse indexes.")
    parser.add_argument("--folder", type=Path, default=ROOT / "knowledgebase")
    parser.add_argument("--index-dir", type=Path)
    args = parser.parse_args()
    try:
        report = KnowledgeStore(args.index_dir).ingest(args.folder)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Ingestion failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

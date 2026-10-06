"""CLI hybrid search preview with no LLM or delivery call."""
import argparse
import json
from dotenv import load_dotenv
from src.knowledge.store import KnowledgeStore, ROOT


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Preview hybrid PDF retrieval.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(KnowledgeStore().search(args.query, top_k=args.top_k), indent=2))


if __name__ == "__main__":
    main()

"""Persistent local memory for facts learned across agent runs."""

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import chromadb
from dotenv import load_dotenv


class LongTermMemory:
    """Store and semantically retrieve facts using a local Chroma database."""

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        collection_name: str = "learned_facts",
    ) -> None:
        load_dotenv()
        configured_path = persist_dir or os.getenv(
            "CHROMA_PERSIST_DIR", "./chroma_data"
        )
        self.persist_dir = Path(configured_path).expanduser()
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def add(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        fact_id: str | None = None,
    ) -> str:
        """Persist one fact and return its ID."""
        if not text.strip():
            raise ValueError("text must not be empty")

        stored_id = fact_id or str(uuid4())
        self.collection.add(
            ids=[stored_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return stored_id

    def query(
        self,
        text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find facts similar to ``text``, including their text and metadata."""
        if not text.strip():
            raise ValueError("text must not be empty")
        if n_results < 1:
            raise ValueError("n_results must be at least 1")

        query_args: dict[str, Any] = {
            "query_texts": [text],
            "n_results": n_results,
        }
        if where is not None:
            query_args["where"] = where
        response = self.collection.query(**query_args)

        ids = response["ids"][0]
        documents = response["documents"][0]
        metadatas = response["metadatas"][0]
        distances = response.get("distances")

        facts = []
        for index, fact_id in enumerate(ids):
            fact = {
                "id": fact_id,
                "text": documents[index],
                "metadata": metadatas[index] or {},
            }
            if distances is not None:
                fact["distance"] = distances[0][index]
            facts.append(fact)
        return facts

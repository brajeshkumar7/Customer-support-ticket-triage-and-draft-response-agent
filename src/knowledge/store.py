"""Persistent dense Chroma + sparse BM25 retrieval with committed generations."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import chromadb
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = "pdf-paragraph-120w-overlap20-bm25-minilm-prefix150-policy-v3"
STOP_WORDS = frozenset("a an the i my you your is are was were be to of for in on at and or it this that do does can could would please".split())


def rag_configuration() -> dict:
    """Read-only benchmark provenance; do not open historical ticket memory."""
    from src.agent.rag import RAG_AGENT_VERSION
    enabled = os.getenv("RAG_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return {"enabled": False, "pipeline": PIPELINE, "agent_version": RAG_AGENT_VERSION, "corpus_sha256": None}
    directory = Path(os.getenv("RAG_INDEX_DIR", str(ROOT / "data/rag_index"))).resolve()
    database = directory / "ledger.sqlite3"
    if not database.exists():
        return {"enabled": True, "pipeline": PIPELINE, "agent_version": RAG_AGENT_VERSION, "corpus_sha256": None}
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        records = db.execute("SELECT path,generation,digest,metadata,chunk_count FROM documents ORDER BY path").fetchall()
    return {"enabled": True, "pipeline": PIPELINE, "agent_version": RAG_AGENT_VERSION,
            "corpus_sha256": hashlib.sha256(json.dumps(records, ensure_ascii=True).encode()).hexdigest()}


def terms(text: str) -> Counter[str]:
    return Counter(word for word in re.findall(r"[\w]+", text.casefold())
                   if word not in STOP_WORDS and len(word) > 1)


def pdf_ledger_identity(path: Path, relative_filename: str) -> str:
    """Identify an immutable PDF by its relative filename and first 150 words.

    Stop extracting pages as soon as the prefix is complete. This intentionally
    does not detect edits after that prefix; revisions must have new filenames.
    Keep the reader on a seekable file rather than loading all bytes into memory.
    """
    words: list[str] = []
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are unsupported; provide an unlocked text PDF.")
        for page in reader.pages:
            words.extend((page.extract_text(extraction_mode="layout") or "").split()[:150 - len(words)])
            if len(words) == 150:
                break
    if not words:
        raise ValueError("PDF has no extractable text; OCR is required before ingestion.")
    payload = json.dumps([relative_filename, words], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pdf_provenance_hash(path: Path) -> str:
    """Full-content provenance check only when indexing, never on a skip."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pdf_chunks(path: Path) -> list[dict]:
    """Keep page provenance and paragraph/sentence boundaries with bounded overlap."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are unsupported; provide an unlocked text PDF.")
    chunks = []
    for page_number, page in enumerate(reader.pages, 1):
        text = page.extract_text(extraction_mode="layout") or ""
        paragraphs = re.split(r"\n\s*\n", text)
        units = []
        for paragraph in paragraphs:
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph.strip()):
                words = sentence.split()
                # Oversized paragraphs/sentences are split rather than silently truncated.
                units.extend(words[i:i + 100] for i in range(0, len(words), 100))
        buffer: list[str] = []
        for unit in units:
            if buffer and len(buffer) + len(unit) > 120:
                chunks.append({"page": page_number, "text": " ".join(buffer)})
                buffer = buffer[-20:]
            buffer.extend(unit)
        if buffer:
            chunks.append({"page": page_number, "text": " ".join(buffer)})
    if not chunks:
        raise ValueError("PDF has no extractable text; OCR is required before ingestion.")
    return chunks


class KnowledgeStore:
    def __init__(self, directory: Path | str | None = None, *, embedding_function=None,
                 collection=None):
        self.directory = Path(directory or os.getenv("RAG_INDEX_DIR", str(ROOT / "data/rag_index"))).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "ledger.sqlite3"
        self.collection = collection
        if self.collection is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self.client = chromadb.PersistentClient(path=str(self.directory / "chroma"))
            self.collection = self.client.get_or_create_collection(
                "pdf_knowledge_v1", embedding_function=embedding_function or DefaultEmbeddingFunction(),
                metadata={"hnsw:space": "cosine"},
            )
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY, generation TEXT NOT NULL, digest TEXT NOT NULL,
                    metadata TEXT NOT NULL, chunk_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, page INTEGER NOT NULL,
                    text TEXT NOT NULL, length INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sparse (
                    term TEXT NOT NULL, chunk_id TEXT NOT NULL, frequency INTEGER NOT NULL,
                    PRIMARY KEY(term, chunk_id));
                CREATE INDEX IF NOT EXISTS sparse_chunk ON sparse(chunk_id);
                CREATE INDEX IF NOT EXISTS chunk_path ON chunks(path);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, folder: Path | str) -> dict:
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise ValueError(f"Knowledge folder does not exist: {folder}")
        lock = self.directory / "ingest.lock"
        # Single writer; a stale lock is explicit and requires operator inspection.
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        report = {"indexed": [], "skipped": [], "removed": [], "errors": []}
        try:
            manifest_path = folder / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
            if not isinstance(manifest, dict):
                raise ValueError("knowledgebase/manifest.json must be an object keyed by relative PDF path.")
            files = sorted(path for path in folder.rglob("*") if path.suffix.lower() == ".pdf" and path.is_file())
            seen = set()
            for path in files:
                relative = path.relative_to(folder).as_posix()
                seen.add(relative)
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(folder):
                        raise ValueError("PDF symlinks outside the knowledge folder are unsupported.")
                    ledger_identity = pdf_ledger_identity(path, relative)
                    metadata = manifest.get(relative, {})
                    if not isinstance(metadata, dict):
                        raise ValueError("PDF manifest entry must be an object.")
                    generation = hashlib.sha256(json.dumps(
                        [ledger_identity, PIPELINE, metadata], sort_keys=True,
                        ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8")).hexdigest()
                    with self.connect() as db:
                        previous = db.execute("SELECT * FROM documents WHERE path=?", (relative,)).fetchone()
                    if previous and previous["generation"] == generation:
                        ids = self.collection.get(where={"generation": generation}, include=[])["ids"]
                        if len(ids) == previous["chunk_count"]:
                            report["skipped"].append(relative)
                            continue
                    digest = pdf_provenance_hash(path)
                    # Only hash-pinned provenance may authorize simulation evidence.
                    trusted = metadata.get("sha256") == digest
                    provenance = {
                        "knowledge_id": str(metadata.get("knowledge_id", "")) if trusted else "",
                        "review_status": str(metadata.get("review_status", "unreviewed")) if trusted else "unreviewed",
                        "knowledge_version": str(metadata.get("knowledge_version", "")) if trusted else "",
                        "approval_scope": str(metadata.get("approval_scope", "unspecified")) if trusted else "reference_only",
                        "source": str(metadata.get("source", relative)),
                        "policy_id": str(metadata.get("policy_id", "")) if trusted else "",
                        "policy_version": str(metadata.get("policy_version", "")) if trusted else "",
                        "policy_sha256": str(metadata.get("policy_sha256", "")) if trusted else "",
                        "rule_ids": metadata.get("rule_ids", []) if trusted else [],
                        "ledger_identity": ledger_identity,
                        "ledger_identity_method": "relative_filename_first_150_words_v2",
                    }
                    chunks = pdf_chunks(path)
                    ids = [hashlib.sha256(f"{relative}:{generation}:{index}".encode()).hexdigest() for index in range(len(chunks))]
                    # Chroma may be partially written on failure. Ledger remains old;
                    # uncommitted generations are never included in a query.
                    for start in range(0, len(chunks), 64):
                        batch = chunks[start:start + 64]
                        self.collection.upsert(
                            ids=ids[start:start + 64], documents=[chunk["text"] for chunk in batch],
                            metadatas=[{"generation": generation, "path": relative, "page": chunk["page"]} for chunk in batch],
                        )
                    with self.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        self._remove(db, relative)
                        db.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (relative, generation, digest, json.dumps(provenance), len(chunks)))
                        for chunk_id, chunk in zip(ids, chunks, strict=True):
                            vector = terms(chunk["text"])
                            db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (chunk_id, relative, chunk["page"], chunk["text"], sum(vector.values())))
                            db.executemany("INSERT INTO sparse VALUES (?,?,?)", [(term, chunk_id, frequency) for term, frequency in vector.items()])
                    report["indexed"].append(relative)
                except Exception as error:
                    # Invalidate old evidence after an update fails; never answer from
                    # a previously indexed version of a now-unreadable source.
                    with self.connect() as db:
                        self._remove(db, relative)
                    report["errors"].append({"document": relative, "error": str(error)})
            with self.connect() as db:
                for row in db.execute("SELECT path FROM documents").fetchall():
                    if row["path"] not in seen:
                        self._remove(db, row["path"])
                        report["removed"].append(row["path"])
        finally:
            lock.unlink()
        return report

    @staticmethod
    def _remove(db, path):
        db.execute("DELETE FROM sparse WHERE chunk_id IN (SELECT id FROM chunks WHERE path=?)", (path,))
        db.execute("DELETE FROM chunks WHERE path=?", (path,))
        db.execute("DELETE FROM documents WHERE path=?", (path,))

    def search(self, query: str, *, top_k: int = 5) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("Search requires a non-empty query of at most 2000 characters.")
        if type(top_k) is not int or not 1 <= top_k <= 12:
            raise ValueError("top_k must be between 1 and 12.")
        with self.connect() as db:
            db.execute("BEGIN")
            documents = {row["path"]: dict(row) for row in db.execute("SELECT * FROM documents")}
            count, average = db.execute("SELECT count(*), avg(length) FROM chunks").fetchone()
            if not count:
                return []
            generations = sorted({row["generation"] for row in documents.values()})
            dense = self.collection.query(query_texts=[query], n_results=min(count, top_k * 4),
                                          where={"generation": {"$in": generations}}, include=["distances"])
            dense_ids = dense["ids"][0]
            distances = dict(zip(dense_ids, dense["distances"][0], strict=True))
            sparse_scores: dict[str, float] = {}
            for term in terms(query):
                postings = db.execute("SELECT s.chunk_id, s.frequency, c.length FROM sparse s JOIN chunks c ON c.id=s.chunk_id WHERE s.term=?", (term,)).fetchall()
                idf = math.log(1 + (count - len(postings) + .5) / (len(postings) + .5))
                for row in postings:
                    frequency = row["frequency"]
                    denominator = frequency + 1.2 * (.25 + .75 * row["length"] / max(average, 1))
                    sparse_scores[row["chunk_id"]] = sparse_scores.get(row["chunk_id"], 0) + idf * frequency * 2.2 / denominator
            sparse_ids = sorted(sparse_scores, key=lambda key: (-sparse_scores[key], key))[:top_k * 4]
            fusion: dict[str, float] = {}
            for ranking in (dense_ids, sparse_ids):
                for rank, chunk_id in enumerate(ranking, 1):
                    fusion[chunk_id] = fusion.get(chunk_id, 0) + 1 / (60 + rank)
            evidence = []
            for chunk_id in sorted(fusion, key=lambda key: (-fusion[key], key))[:top_k]:
                row = db.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
                if row is None:
                    continue
                doc = documents[row["path"]]
                evidence.append({"chunk_id": chunk_id, "document": row["path"], "page": row["page"],
                                 "text": row["text"], "document_sha256": doc["digest"],
                                 **json.loads(doc["metadata"]), "rrf_score": fusion[chunk_id],
                                 "dense_distance": distances.get(chunk_id), "sparse_score": sparse_scores.get(chunk_id, 0)})
            return evidence

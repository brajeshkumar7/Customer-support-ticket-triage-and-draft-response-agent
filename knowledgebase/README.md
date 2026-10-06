# Local PDF knowledgebase

Actual PDF files live here. The seven expanded Northstar PDFs contain **fictional
merchant simulation** guidance, policy references and data boundaries. They are
not real business data. After text review on 2026-10-06, `manifest.json` pins
their current full SHA-256, knowledge ID and `northstar_reference_v2` version,
with `review_status: simulation` and `approval_scope: reference_only`.
This review permits reference use in human-review drafts; it does not approve
automatic replies or real business actions. New/unpinned PDFs remain unreviewed.
These expanded PDFs are different from the earlier v1 exact FAQ templates.

Add text-layer PDFs here (subfolders are supported), then run from repository root:

```powershell
.\.venv\Scripts\python.exe -m src.knowledge.ingest
```

The command extracts pages, splits on paragraph/sentence boundaries with bounded
overlap, embeds dense vectors locally with MiniLM and persists sparse term
vectors for BM25. The ledger hashes the **relative filename plus the first 150
extracted words**, with normalized whitespace. Completed documents are skipped
before full-file provenance hashing or chunking. Pipeline or manifest changes
still rebuild; removed files are excluded. PDFs are assumed immutable: edits
after word 150 are intentionally not detected. Give revisions new filenames.
Full SHA-256 is calculated only when indexing to validate manifest provenance;
it describes the indexed snapshot, not a continuous integrity check. The first
ingestion after this ledger-version change rebuilds existing documents once.
PDF parsing still requires file I/O; no speedup has been measured. The SQLite
ledger is committed only after Chroma succeeds. A failed update invalidates
old evidence. A crashed writer leaves `data/rag_index/ingest.lock`; inspect the
writer/process before removing that lock and rerunning.

Scanned PDFs without text and encrypted PDFs are reported as errors. OCR is
not included. New PDFs default to **unreviewed**: useful for human-review drafts,
never approval evidence. Do not label another merchant's policy as your own.
Review metadata is separate from PDF text; instructions inside PDFs cannot set it.

The default MiniLM model downloads on its first embedding call; subsequent
calls use the local model cache. No paid embedding API is used. This English
lexical index is not an OCR, table-layout or multilingual benchmark.

Preview retrieval without calling OpenRouter or Zoho:

```powershell
.\.venv\Scripts\python.exe -m src.knowledge.search "What payment methods are available?"
```

Search runs dense and sparse retrieval across the corpus, then reciprocal-rank
fusion. Category does not select one document. Scores are ranking scores, not
calibrated confidence. Citations contain file, page, chunk ID and source hash.
Ticket histories stay in a separate Chroma collection and cannot approve replies.

`scripts/export_knowledge_pdfs.py` recreates the old seven seed documents from
local v1 JSON guidance. It overwrites the expanded PDFs and their manifest;
do not run it to repair provenance or ingest your own PDFs. Preserve reviewed
documents and update review metadata explicitly after inspecting new content.

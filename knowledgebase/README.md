# Local PDF knowledgebase

This directory contains **13 actual text-layer PDFs**, not links:

| Documents | Count | Provenance / scope |
| --- | --- | --- |
| Expanded Northstar references | 7 | Fictional simulation, `northstar_reference_v2`, reference-only |
| Exact informational reply documents | 4 | Hash-pinned simulation guidance, `automatic_reply_simulation`; exact reply validation still required |
| Generated return and damage policy references | 2 | `fictional_support/v1`, reference-only, derived from the validated shared policy |

[manifest.json](manifest.json) records knowledge IDs, versions, source hashes,
review status and approval scope. New or unpinned PDFs are unreviewed; their
text cannot grant itself approval. Simulation review is **not merchant approval**.
Public research does not establish an order's status or this merchant's policy.

## Shared policy source

[../data/policies/support_v1.json](../data/policies/support_v1.json) supplies both
the policy checker and generated policy PDFs: delivered-only eligibility,
inclusive 30-day returns and inclusive 7-day damage reporting. Safety incidents
and exceptions require human review independently of window eligibility.
The source loader rejects invalid/unavailable policy rather than falling back
to hardcoded rules.

Checker results and active chunks carry policy ID, version, source SHA-256 and
rule IDs. When RAG is enabled and a policy result is used, missing or conflicting
metadata blocks approval. Superseded return/damage PDFs remain on disk but are
excluded from current-policy drafting evidence. Business policy version and
send-safety `informational_only_v4` version describe different things.

## Export, index and search

From the repository root, after Python setup:

```powershell
python -m src.knowledge.export_policy
python -m src.knowledge.ingest
python -m src.knowledge.search "What is the damage-report window?" --top-k 5
```

Policy export merges manifest entries and skips identical completed documents.
Changed content under an existing policy/PDF version fails clearly: author a
new version and extend the validated loader's supported versions before adoption.
The two generated PDFs remain references, not automatic business-action authority.

Ingestion extracts pages, chunks paragraphs/sentences with bounded overlap,
embeds MiniLM dense vectors in separate local Chroma, and stores sparse BM25
vectors and a ledger in SQLite. Search combines rankings with reciprocal-rank
fusion; category is a hint, not a one-category/one-document mapping. Scores
are ranking scores, not calibrated probabilities. Citations include file, page,
chunk ID and source hash. The initial embedding call may download MiniLM;
these CLIs do not call OpenRouter or Zoho.

## Immutable-document lifecycle

The skip key hashes the **relative filename plus first 150 extracted words**
with normalized whitespace. Completed documents skip full provenance hashing
and chunking; pipeline/manifest changes can rebuild them. Revisions require new
filenames: changes after word 150 deliberately are not detected. Full PDF hashes
validate provenance when indexing, not continuously. Deleted or failed sources
are excluded; only committed generations are searched.

The ledger commits after Chroma succeeds. A crashed writer may leave
`data/rag_index/ingest.lock`; verify no writer is active before removing a stale
lock. Scanned PDFs without a text layer and encrypted PDFs are errors; OCR is
not included. Larger-corpus, multilingual and table extraction remain unmeasured.
Historical summaries live in separate Chroma and are never approval evidence.

The optional `scripts/export_knowledge_pdfs.py` and
`scripts/export_simulation_reply_pdfs.py` are authoring utilities. They **refuse
to overwrite existing target PDFs** and merge manifest entries. They are not
ordinary setup or provenance-repair commands. Preserve expanded references.

See [the root command guide](../README.md) and
[knowledge audit](../docs/knowledge_audit.md) for measurements and limitations.

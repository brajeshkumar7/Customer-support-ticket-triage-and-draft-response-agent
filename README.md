# Support Ticket Triage Agent

A local, stateful support-ticket agent with Jev triage, hybrid PDF RAG,
deterministic safety decisions, cited drafts, structured review, bounded
retries, and observable outcomes. This is a measured portfolio project,
**not approved for unattended real-customer delivery**.

TASK-43: 50 attempted, 50 scored, 47 matched; disposition match 0.94; 0 false simulated sends, 3 false escalations, 0 operational failures. Full-run p95: 52145.7439000078 ms; reported token cost: 0.245525665. See [TASK-43 measurement](docs/measurements/task43_regression.json). These are author-labeled synthetic development results, not independent real-customer validation. Older measurements remain historical.

## Guides

- [Project instructions](AGENTS.md), [specification](PRD.md), [tasks](TASKS.md)
- [Architecture](docs/architecture.md), [three explained workflows](flow.md)
- [Knowledgebase](knowledgebase/README.md), [dataset](data/test_tickets/README.md)
- [Decisions](DECISIONS.md), [measurements and progress](PROGRESS.md), [failures](FAILURE_MODES.md)
- [Readiness gaps](PRODUCTION_READINESS.md), [optional controlled worker](docs/controlled_render.md)

## 1. Setup

Run commands from the repository root unless a section explicitly changes
folders. Prerequisites: Python **3.11+**, Git, and internet access for package
installation. The optional dashboard needs Node **20.9+** and npm. PostgreSQL
and Zoho are unnecessary for synthetic runs. Docker, Redis, and Ollama are not
wired into the local workflow; their legacy example settings do not enable them.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

If Python 3.11 is not installed, select an installed Python 3.11+ interpreter.
The activation path is `.\.venv\Scripts\Activate.ps1`, with both dots separated
by a backslash. If script execution is blocked, optionally allow scripts only
for this terminal, then activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Activation is optional: substitute `.\.venv\Scripts\python.exe` for `python`
in every Python command below. Do not commit `.venv/` or `.env`.

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

Use a Python 3.11+ `python3`. Without activation, use `.venv/bin/python`.

### Configuration

Edit `.env`, keeping credentials out of `.env.example` and Git. The examples
below use placeholders; they are not account settings.

| Group | Settings and requirements |
| --- | --- |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_PRIMARY_MODEL`, `OPENROUTER_MODELS` (chat fallbacks); use the models you choose, free or paid |
| Decisions | `OPENROUTER_TRIAGE_MODEL`, `OPENROUTER_SUPERVISOR_MODEL`; defaults are `typesafe/jev-1.13`; chat fallbacks do not replace Jev |
| Limits | `OPENROUTER_REQUESTS_PER_MINUTE`, `OPENROUTER_TIMEOUT_SECONDS`, `AGENT_RUN_TIMEOUT_SECONDS`; bounded API retries are separate from three graph retries |
| Knowledge | `RAG_ENABLED=true`, `RAG_INDEX_DIR=./data/rag_index`; ingest before graph evaluations |
| Logging | `LOG_LEVEL`; local JSONL is under `data/logs/`; dashboard `LOGS_DIR` is configured separately |
| Historical memory | `CHROMA_PERSIST_DIR`; ordinary sample/Zoho runs persist summaries; synthetic commands use ephemeral memory |
| Zoho, optional | Regional `ZOHO_DESK_API_DOMAIN`, `ZOHO_ACCOUNTS_DOMAIN`, `ZOHO_DESK_ORG_ID`, `ZOHO_DESK_FROM_EMAIL`, OAuth client ID/secret and refresh token; ticket READ/UPDATE scopes as needed |
| Sending | Keep `ZOHO_DESK_SEND_ENABLED=false` unless deliberately using a controlled reviewed-email or smoke command; this flag never enables graph auto-send |
| Worker, optional | `DEPLOYMENT_MODE=off`, `DATABASE_URL`, `APPROVED_KNOWLEDGE_SHA256`; see deployment guide for additional owner review and allowlist requirements |

Model-backed commands consume configured OpenRouter quotas and may incur cost.
A probability is a model output, not calibrated proof of correctness.

## 2. Prepare and inspect knowledge

The checked-in corpus has **13 PDFs**: seven expanded fictional references,
four exact informational simulation replies, and two generated business-policy
references. References and unreviewed documents cannot authorize an automatic
reply. Full provenance and approval scopes are in
[the knowledgebase guide](knowledgebase/README.md).

```powershell
python -m src.knowledge.export_policy
python -m src.knowledge.ingest
python -m src.knowledge.search "How long does an approved refund take?" --top-k 5
```

Export is offline and derives reference PDFs from
[data/policies/support_v1.json](data/policies/support_v1.json), the same validated
source as the policy checker. It skips identical completed exports, merges
manifest entries, and refuses changed content under an existing policy/PDF
version. Ingestion writes dense local MiniLM vectors to Chroma and sparse BM25
vectors/ledger to SQLite. Its first embedding call may download MiniLM; it does
not call OpenRouter or Zoho. Search prints local ranked chunks and citations.

Immutable documents are identified by relative filename plus the first 150
words. Later edits are not detected by that skip key: give revisions new
filenames, inspect provenance/scope, then ingest. Full PDF hashes are checked
when indexing. Do not relabel public reference guidance as merchant authority.
Superseded return/damage references stay on disk but are excluded from active
policy evidence. Business policy `fictional_support/v1` is distinct from send
policy `informational_only_v4`.

These **authoring utilities are unnecessary for normal setup** and refuse
existing target PDFs; do not use them as a repair/overwrite command:

```powershell
python scripts/export_knowledge_pdfs.py
python scripts/export_simulation_reply_pdfs.py
```

Do not regenerate the frozen holdout with `src.eval.build_holdout` for an
ordinary run; changing its bytes invalidates its pinned version/hash.

## 3. Run the local agent

### Single synthetic ticket

```powershell
python -m src.agent.run_synthetic --case-id general_07
python -m src.agent.run_synthetic --case-id return_01
```

Select any ID from `tickets.jsonl` (for example `order_01`–`order_10`). These
commands use configured models, the local PDF index, fresh ephemeral Chroma,
and a **fake sender only**. No Zoho request or email occurs. A covered FAQ may
be simulated; customer-specific requests produce human-review drafts and
escalations. Outcomes print to the console; events go to `data/logs/`.

### Sample and streaming demonstration

```powershell
python -m src.agent.graph
python -m src.agent.stream_example
```

Both use OpenRouter and persistent historical memory. Neither provides a Zoho
ticket ID or a fake sender, so no real email is sent; an unavailable delivery
ends in escalation. Streaming prints each completed node's partial update
with flushing, not token-by-token output. Events are also logged locally.

### All 50 development regression tickets

```powershell
python -m src.eval.run_eval
```

This runs configured models with **simulated delivery only**, using
`manifest_informational.csv`, not the older fixture-backed labels. No Zoho
mapping, credentials, or `--send` flag is needed or supported. Each batch gets
a fresh shared ephemeral Chroma collection; successful simulations can supply
historical context to later cases. Persistent history is untouched.

The console prints per-case outcomes and metrics. Raw reports are saved in
`data/eval_reports/`; model/tool events go to `data/logs/events.jsonl`. Only
fully scored batches publish accepted tracker metrics. A failed batch is still
saved and must not be described as a clean accuracy result.

### 200-case synthetic regression and checkpoint resume

```powershell
python -m src.eval.run_holdout
python -m src.eval.run_holdout --resume data/eval_reports/HOLDOUT_CHECKPOINT.json
```

Use the actual checkpoint path printed by the runner. Configured models and a
fake sender are used; there is no Zoho delivery. Memory is shared ephemerally
within the batch and successful summaries are restored on resume. The runner
checks frozen dataset bytes and configuration compatibility, including RAG,
models, review threshold, and business policy. It rejects incompatible resumes.
These are **author-labeled synthetic cases**, not independently reviewed real
tickets; prior tuning makes them a regression set rather than an untouched
holdout. Reports/checkpoints are local under `data/eval_reports/`.

### Recompute saved metrics offline

```powershell
python -m src.eval.run_eval --report data/eval_reports/REPORT.json
python -m src.eval.run_holdout --report data/eval_reports/HOLDOUT_REPORT.json
```

Use an existing report path. These commands print its recorded metrics without
new model calls, Zoho requests, or duplicate replies. Historical 25-ticket
reports remain readable; their measurements do not describe the current stack.

## 4. Controlled Zoho runs

Use the **numeric API `id`**, not the visible ticket number such as `#101`.
Obtain it from Zoho's ticket API or the ticket's API identifier. Do not substitute
an order ID. Use only tickets and contacts you control.

### Fetch and draft, without email

```powershell
python -m src.agent.run_zoho --ticket-id 123456789 --draft-only
```

Requires Zoho read credentials, OpenRouter configuration and an ingested index.
After CONTROLLED and ticket-ID confirmation, it fetches subject/description
and runs the local graph with persistent Chroma. Usable text can be analyzed
across channels. This command neither sends nor assigns a ticket. It does not
use the worker's latest-inbound-thread polling path. Console results include
run ID, triage, safety findings, draft, and structured supervisor review.

### Run the agent, then manually confirm one email

```powershell
python -m src.agent.run_zoho --ticket-id 123456789 --send-reviewed
```

Requires the same configuration, update permissions, sender address and
`ZOHO_DESK_SEND_ENABLED=true`. The graph itself stays draft-only. The separate
CLI step shows the exact outgoing text and fetched requester email:

- A supervisor-approved draft is proposed for explicit human review, even if
  the deterministic gate blocked unattended delivery.
- If the draft fails review or is absent, a **fixed acknowledgement** is
  proposed instead; it does not repeat unverified agent facts.
- Confirm the displayed requester email exactly (not your support address),
  then the requested SEND/ticket confirmation. The command rechecks ticket
  text, recipient and status before attempting at most one public reply.

Declined/mismatched confirmation sends nothing. An uncertain timeout is not
retried: inspect Zoho before sending manually. The reviewed-email outcome is
separate from the graph's escalation status. API acceptance/thread confirmation
does not prove inbox arrival; check the ticket conversation and recipient inbox.
The old `run_zoho --send` is superseded.

### Delivery-only fixed-message smoke test

```powershell
python -m src.eval.zoho_smoke --ticket-id 123456789 --send
```

Requires enabled controlled sending and Zoho credentials. After controlled
contact and ticket confirmation it attempts one fixed message. **No agent,
OpenRouter, or RAG runs**. Console and JSONL record delivery; ambiguous sends
are not retried. This tests the adapter, not agent accuracy.

## 5. Tests and additional evaluations

### Sequential/concurrent comparison (TASK-20)

```powershell
python -m src.eval.compare_tool_dispatch
python -m src.eval.compare_tool_dispatch --report data/eval_reports/TASK20_REPORT.json
```

The first command runs two fresh 50-ticket batches with configured models
(paid calls if selected): sequential fixture dispatch first, concurrent second.
Both use only fake delivery and separate fresh shared ephemeral Chroma; no
Zoho calls or emails. Ordinary commands still default to concurrent dispatch.
Existing RAG and informational bypasses are unchanged. Reports/checkpoints
are saved in `data/eval_reports/task20_*.json`; the second command recomputes
offline. Interrupted batches are diagnostics, with no automatic paid restart.
Dispatch timings exclude RAG/extraction; full-run differences also include
model variation, pacing and cache effects. Automatic comparison-row publication requires two
complete scored batches and is separate from the ordinary accuracy tracker.

The latest [comparison attempt](docs/task20_comparison.md), completed 2026-10-08,
attempted all 100 runs: sequential 32 scored/31 matched with 18 operational
failures; concurrent 49 scored/47 matched with one failure. Both recorded zero
false simulated sends. Its subset latencies are diagnostic, with no accepted
speedup or tracker replacement. TASK-20 remains open. The earlier FM-029
checkpoint defect was fixed offline before this attempt; no paid batch was
automatically restarted.

| Command | Configuration / external calls | Output and scope |
| --- | --- | --- |
| `python -m pytest tests -q` | Installed Python dependencies; fake clients, no live model or email calls | Console results; network-free implementation regressions |
| `python -m pytest tests/test_business_policy.py -q` | Offline | Shared-policy boundaries and metadata checks |
| `python -m src.eval.run_safety_regressions` | Offline | Console; historical fixture-gate checks, not current approval acceptance; use pytest for current rules |
| `python -m src.eval.run_prompt_injection_eval` | Configured graph models plus first configured fallback as judge; Zoho forced off | Ten cases, console verdicts and JSONL; no standalone report or automatic PRD metric publication |
| `python -m src.eval.run_supervisor_eval` | Configured Jev supervisor; no Zoho | Nine visible labeled development drafts; console, logs and `data/eval_reports/task38_reviews_*.json`; not an independent calibration set |
| `python -m src.eval.compare_classification --report docs/measurements/combined_classification_20261004.json` | Offline historical experiment recomputation | Prints and writes `data/eval_reports/combined_classification_comparison.json`; compares old generative paths, not Jev |
| `python -m src.eval.run_release_eval --cases data/test_tickets/release_reviewed.jsonl --out data/eval_reports/release_review.json` | Offline; requires an externally reviewed dataset that is not supplied | Deterministic policy evaluation; requires at least 200 attributed reviews and category coverage; does not test delivery or arrival-to-reply latency |
| `python -m src.eval.export_public_metrics data/eval_reports/REPORT.json docs/measurements/NEW_SUMMARY.json` | Offline; existing fully scored 50/200 report required | Writes body-free derived metrics; refuses unscored reports and existing outputs unless `--overwrite` is explicitly supplied |

Running classification comparison without `--report` makes configured model
calls for the historical experiment. It is optional, not a current Jev test.
Public export cannot publish TASK-41 as an accepted report because it contains
operational failures. Raw reports may contain ticket text and drafts.

## 6. Dashboard

Read-only Next.js App Router + strict TypeScript. It reads JSONL server-side,
with file selection, run-ID filtering, skipped-line counts and expandable event
values. This is a local debugger, not a customer portal.

```powershell
cd dashboard
npm install
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Open `http://localhost:3000`. `LOGS_DIR` defaults to `../data/logs`, resolved
relative to `dashboard/`. On Linux/macOS replace the copy command with
`[ -f .env.local ] || cp .env.example .env.local`. No model/Zoho calls or log
writes occur. Rendered log values are visible in your browser.

```powershell
npm run lint
npm run build
npm run start
cd ..
```

Stop the dev server before `start` on the same port. `start` requires a build.
Files in `node_modules/` and `.next/` are ignored. Status is per event; missing
status evidence shows `—`, not an inferred run success.

## 7. Optional controlled worker administration

The worker is **implemented but undeployed**, separate from the local graph.
It needs PostgreSQL, Zoho credentials and a deliberate paid infrastructure
setup; [read the complete prerequisites](docs/controlled_render.md) first.
`live` fails startup. Do not enable paid infrastructure just to run evaluation.

```powershell
python -m src.agent.production_worker
```

With `DEPLOYMENT_MODE=off` it waits without polling. `shadow` polls Zoho and
records database decisions without Zoho writes. `test` requires owner-approved
knowledge with a matching hash, exact ticket/contact allowlisting and an
enabled database kill switch. It can send approved informational templates or
route blocked cases through private notes. No model drafting or Chroma approval
is used. Ctrl+C stops a local worker. Logs omit bodies; jobs persist in the DB.

After owner review, compute the knowledge hash, configure test mode and the
required DB/Zoho settings. The administration commands write PostgreSQL:

```powershell
Get-FileHash data/approved_knowledge/v1.json -Algorithm SHA256
$testExpiry = (Get-Date).ToUniversalTime().AddDays(1).ToString("yyyy-MM-ddTHH:mm:ssZ")
python -m src.agent.worker_admin allow-test-ticket --ticket-id 123456789 --email controlled@example.com --expires $testExpiry
python -m src.agent.worker_admin enable-test-sending
python -m src.agent.worker_admin disable-test-sending
python -m src.agent.worker_admin mark-reviewed --ticket-id 123456789 --thread-id 987654321
```

`enable-test-sending` permits a running test worker to send; do not run it
casually. The disabling command is the kill switch. Mark a human/unknown job
reviewed only after inspecting Zoho; it records resolution, not a resend.
Administration initializes required tables; it needs `DEPLOYMENT_MODE=test`.

## 8. Where to inspect results

- **Console:** single-ticket draft, triage, safety and supervisor findings;
  streaming prints completed node updates as they arrive.
- **`data/logs/events.jsonl`:** correlated node/tool/model events, latency and
  available provider cost. Local logs can contain ticket bodies and drafts;
  keep them private. Missing costs remain unknown, not zero.
- **`data/eval_reports/`:** raw per-case reports/checkpoints, including failed
  batches; recompute with the matching `--report` command.
- **`docs/measurements/`:** committed body-free historical measurements and
  failure diagnostics. Failed diagnostics are not accepted benchmark metrics.
- **[PROGRESS.md](PROGRESS.md):** current report-backed tracker, historical measurements and dated sessions.
- **Dashboard:** individual JSONL events, not independent correctness verdicts.

## 9. Measured results and remaining limits

Separately, [manual Zoho integration observations](docs/zoho_manual_validation.md)
record owner-shared OAuth, ticket lookup, historical delivery, safety blocks,
recipient confirmation and acknowledgement receipt. These controlled manual
tests are excluded from the synthetic accuracy metrics below.

[TASK-43 measurement](docs/measurements/task43_regression.json), measured 2026-10-07. Raw local report: `data/eval_reports/task29_20261007T095641Z_d2289193.json`.

| Metric | Recorded value |
| --- | --- |
| Attempts / scored / matched | 50 / 50 / 47 |
| Disposition match | 0.94 |
| Category classification | 46/50 = 0.92 |
| False simulated sends / false escalations | 0 / 3 |
| Operational failures | 0 |
| Simulated replies | 4 |
| Full-run p95 latency | 52145.7439000078 ms |
| Total provider-reported token cost | 0.245525665 |
| Mean retries-to-success | 0.0 |
| Tickets with missing token cost | 0 |

Disposition mismatches: `general_03`, `general_04`, `general_08`. The 95% disposition target is not met in this run; no production acceptance follows. Current 200-case validation, sequential/async comparison, larger-corpus performance and live-release gates remain open. Historical TASK-41 failures are preserved in its diagnostic; absence of an operational failure here does not prove a parsing defect was fixed.

Recorded examples include:

- **FM-005:** injected manager approval entered a draft; field allowlisting and
  the measured post-fix run are preserved in the failure log.
- **FM-022:** Jev rejected supported development drafts; the provisional review
  threshold is not independently calibrated.
- **FM-026/028:** response/fact-gathering validation failed in current benchmark
  attempts; these are operational failures, not successful dispositions.

See [FAILURE_MODES.md](FAILURE_MODES.md) for exact observations and before/after
records. Real automation still needs merchant
approval, authoritative business data, identity checks, representative independent
review, and operational validation. Customer-specific fixture data and historical
Chroma summaries cannot authorize a real reply.

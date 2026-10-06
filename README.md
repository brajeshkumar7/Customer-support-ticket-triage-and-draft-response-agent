# Support Ticket Triage Agent — Multi-Step Runtime Safety

> Status: in progress. See `TASKS.md` for current phase, `PROGRESS.md` for the
> latest session log.

A stateful, multi-step support agent with fixed application-owned tools,
async concurrency, observability, and tested prompt-injection defenses. The
Docker tool runner is a placeholder; current tools run in the Python process.
The controlled Zoho worker can send only approved informational templates to
allowlisted test contacts. Real customer auto-send is disabled.

## Project files (read in this order)

1. `AGENTS.md` — instructions for AI coding tools (Codex, Cursor, Antigravity all read this)
2. `PRD.md` — full spec: goals, architecture, success metrics
3. `TASKS.md` — current task breakdown by phase
4. `DECISIONS.md` — architecture decisions and why they were made
5. `PROGRESS.md` — session-by-session log and measured metrics

## Setup

Use Python 3.11 or newer. Create and activate a project-local virtual
environment before installing or running the project. The `.venv/` directory
is ignored by Git; the dependency source of truth remains `requirements.txt`.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
python -m pytest
```

Fill in `.env` with the required local settings and API credentials before
running the graph manually. The Zoho agent workflow is currently draft-only:
it cannot send a public reply even if `ZOHO_DESK_SEND_ENABLED=true`. The
separate `zoho_smoke` command remains a delivery-only test requiring explicit
confirmation. Zoho is the current replaceable reply adapter.
Configure the Zoho API and Accounts domains,
organization ID, a configured support sender email, OAuth client ID/secret,
and refresh token; the OAuth app needs `Desk.tickets.READ` and
`Desk.tickets.UPDATE` scopes. The draft-only Zoho command takes a numeric
Zoho API ticket ID. Tests use mocked clients and never send live replies. If PowerShell
blocks activation scripts, use
`.venv\Scripts\python.exe -m pip install -r requirements.txt` and
`.venv\Scripts\python.exe -m pytest` without activating the environment.

## Run-history dashboard

The local read-only dashboard uses Next.js and TypeScript and reads the agent's
JSONL files from `data/logs/` on the server. From the repository root, start it
with:

```powershell
cd dashboard
npm install
npm run dev
```

Open <http://localhost:3000>. To read logs from another location, set
`LOGS_DIR` in `dashboard/.env.local`; see [`dashboard/README.md`](dashboard/README.md).

## Stream graph updates

With the OpenRouter settings configured in `.env`, run the sample workflow and
print each completed node update as it arrives:

```powershell
.\.venv\Scripts\python.exe -m src.agent.stream_example
```

The sample does not include a Zoho ticket ID, so it cannot post a reply.

## Evaluate the synthetic tickets

Run all 50 current cases through the graph with a fake sender. The new
informational-only labels are in `data/test_tickets/manifest_informational.csv`;
the original `manifest.csv` and its 50/50 report are historical:

```powershell
.\.venv\Scripts\python.exe -m src.eval.run_eval
```

The fake sender lets the evaluator measure approved-reply and escalation
decisions without creating Zoho tickets or posting public replies. A simulated
send is not evidence of real delivery. The run saves a report in
`data/eval_reports/` and updates `PROGRESS.md` with measured results. To
recompute a saved report without external calls:

```powershell
.\.venv\Scripts\python.exe -m src.eval.run_eval --report data/eval_reports/REPORT.json
```

Each full evaluation uses one fresh, shared, in-memory Chroma collection in
ticket order. Successful simulated runs store compact summaries that later
cases may recall. The configured persistent Chroma database is untouched.
Reports identify this as `shared_ephemeral_chroma_sequential`; older reports
did not record effective recall mode and remain historical comparisons only.
The old implementation created an ephemeral client per ticket, but Chroma
reuses a shared in-process ephemeral database; the 200-case run also evaluated
parallel batches. Its exact recall exposure is unknown.

Run the separate frozen 200-case author-labeled synthetic holdout:

```powershell
.\.venv\Scripts\python.exe -m src.eval.run_holdout
```

This uses the configured models and a fake sender. It checks the holdout's
SHA-256 and saves per-case reasons, evidence, latency, model calls, and cost.
The labels are author-drafted and templated, not independently reviewed. It
does not call Zoho. A new complete run uses one fresh ephemeral Chroma
collection shared in ticket order; later cases can recall prior successful
summaries, and persistent Chroma is untouched. The older saved holdout ran
parallel batches and did not establish its exact recall exposure. The runner uses
one OpenRouter client and rate budget; per-ticket latency includes request
pacing waits. Progress is
checkpointed after each case in
`data/eval_reports/`; if interrupted, resume with
`python -m src.eval.run_holdout --resume data/eval_reports/CHECKPOINT.checkpoint.json`.
Resume refuses a changed approval policy, knowledge file, or model selection;
start a new run after any of those changes.
`--report PATH` recomputes a completed saved report offline.

### Run one synthetic ticket (Flow 1)

Run a single case through the current graph. Covered general FAQ questions
use an exact versioned reply without model or mock business-tool calls;
other tickets can produce a human-review draft and escalation:

```powershell
.\.venv\Scripts\python.exe -m src.agent.run_synthetic --case-id order_01
```

Choose any ID from `data/test_tickets/manifest_informational.csv`. This command uses an
isolated in-memory Chroma client and a fake reply sender. It makes no Zoho
calls. A passing reply is labeled **simulated**; an unsafe or failed run
returns an escalation. The printed triage fields include category, urgency,
priority, and which rule or classifier supplied them. It does not prove that a
customer email was delivered.

### Run one existing Zoho ticket through the agent (draft-only)

Use only a test ticket and contact you control. The command fetches an existing
Zoho ticket and runs classification, fact gathering, drafting, deterministic
safety checks, and supervisor review. It cannot send, even when the environment
setting enables sending:

```powershell
.\.venv\Scripts\python.exe -m src.agent.run_zoho --ticket-id YOUR_TICKET_API_ID --draft-only
```

The command asks you to confirm ownership and retype the ticket API ID. It
then fetches that existing ticket from Zoho, accepts Email tickets with a
usable description, and supplies the subject and message to the same agent
workflow. The result includes the draft and deterministic safety findings for
review, plus predicted category, urgency, and a sortable priority band
(`P1` is highest, then `P2`, then `P3`). Explicit high-stakes or time-critical
wording can raise a ticket's priority. These bands are per-ticket triage
metadata; they do not promise an SLA or place tickets into a shared queue. The
legacy `--send` flag is rejected. This command never creates
tickets or posts public replies. Repeat it separately for each controlled
test ticket.

The local runner can log ticket text and drafts in `data/logs/`; use only
controlled test data. The deployed worker uses metadata-only logging.

## Controlled automatic-reply worker

The optional paid Render/PostgreSQL deployment is documented in
[`docs/controlled_render.md`](docs/controlled_render.md). Its mode defaults to
`off`. In `shadow` it polls Zoho without sending. In `test` it can send one
versioned informational template to an exact, unexpired ticket/contact
allowlist entry after an owner approves the reference text and enables the
database kill switch. It uses the latest inbound Email thread, checks ticket
and recipient again before sending, and never automatically retries an
uncertain reply. Other categories go to a human queue/private note.

The worker and graph now share the same informational-only approval rule and
versioned knowledge entries. They do not use LLM prose, local mock orders, or
unscoped Chroma memories in public replies. The local knowledge file remains
`review_required`; controlled worker sending needs owner-approved text and an
exact allowlist. Real customer mode deliberately
fails startup until authoritative business data, reviewed cases, shadow
evidence, and a separate release decision exist.

The [local knowledge audit](docs/knowledge_audit.md) inventories what the
agent actually retrieves and what remains synthetic. Public research sources
are recorded in `data/knowledge_sources.json` for review; they are not
approved merchant policy or evidence for automatic replies.

For a future 200-case human-reviewed release set, run the offline policy
evaluator with a reviewed JSONL file:

```powershell
.\.venv\Scripts\python.exe -m src.eval.run_release_eval --cases data/test_tickets/release_reviewed.jsonl --out data/eval_reports/release_review.json
```

This command refuses fewer than 200 cases or missing reviewer attribution.
It does not measure Zoho delivery or arrival-to-reply latency. Neither the
current simulated graph benchmark nor the author-labeled holdout is a release
gate for live customers. Saved 25-ticket reports remain historical. The
earlier fixture-backed 50-ticket fake-sender post-fix run recorded 50/50 expected
dispositions matched, with zero false simulated sends among 28 expected
escalations under a broader approval policy. Its labels differ from the new
informational-only manifest. The prior 46/50 report remains in `data/eval_reports/` as the
before measurement. Neither run sent a public reply or validates real customer
automation; authoritative business data and independently reviewed release
cases remain prerequisites.

The 25-ticket one-call classification experiment is recorded in
[`docs/measurements/combined_classification_20261004.json`](docs/measurements/combined_classification_20261004.json).
The combined call was faster but below the 95% category gate, so the graph
still uses the existing two-call path. Recompute its switch decision without
model calls with
`python -m src.eval.compare_classification --report docs/measurements/combined_classification_20261004.json`.
### Test Zoho delivery only (no agent workflow)

Use an existing ticket and contact you control. Set `ZOHO_DESK_SEND_ENABLED=true`
in `.env`, then run:

```powershell
.\.venv\Scripts\python.exe -m src.eval.zoho_smoke --ticket-id YOUR_TICKET_API_ID --send
```

This separate command does not run the agent. It requires confirming that
the ticket/contact are controlled and then typing the ticket ID. It sends one
fixed public smoke-test message. Do not use a customer ticket. The smoke test
does not create tickets or retry an ambiguous send.

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
pytest
```

The Docker image installs the same `requirements.txt` inside its own
container environment; the host `.venv` is for local development and tests.

## Results

The latest completed 50-case measurement uses the configured OpenRouter model
and a fake sender. It predates the final TASK-32 triage edit, so current-version
accuracy still needs a fresh complete run.
The original 50-case manifest and the 200-case holdout are author-labeled,
templated synthetic datasets; the holdout is not independently reviewed. The
results below are local regression evidence, not a production-accuracy claim.
Public-safe per-case summaries are in
[`docs/measurements/task29_50_v3.json`](docs/measurements/task29_50_v3.json) and
[`docs/measurements/task29_holdout_v1.json`](docs/measurements/task29_holdout_v1.json).
Detailed reports, including draft text, remain local under `data/eval_reports/`.

| Metric | Result |
|---|---|
| Latest completed 50-case disposition match | 50/50 = 1.0; 0 false simulated sends; 0 false escalations; 7 simulated replies and 43 escalations |
| Latest completed 50-case p95 / sequential comparison | 44778.41449999687 ms / not measured |
| Latest completed 50-case total cost / cost per matched run | 0.115013845 / 0.0023002769000000003 provider-reported units |
| Latest completed 50-case model attribution | 172 calls on `openai/gpt-6-luna-pro`; no fallback model calls logged |
| 200-case author-labeled holdout match | 189/200 = 0.945; below the 0.95 target |
| 200-case holdout false sends / false escalations | 0 / 11 (all in general questions) |
| 200-case holdout unsupported public claims | 0; evidence covered 21/21 simulated replies |
| 200-case holdout overall p95 / approved FAQ p95 | 59722.046200000026 ms / 714.4188000002032 ms |
| 200-case holdout total cost / cost per matched run | 0.45285409 / 0.0022546855026455027 provider-reported units |
| 200-case holdout model attribution | 716 calls on `openai/gpt-6-luna-pro`; no fallback model calls logged |
| Prompt-injection defense | TASK-17: 10 scored / 0 unsafe after a TASK-16 run with 1 unsafe; see `PROGRESS.md` |

The holdout missed the 95% disposition target because 11 informational general
questions were escalated. Zero false sends and zero unsupported claims are
positive safety measurements, but do not offset the misses or establish
production readiness. Per-category cost, latency, calls, and the model
breakdown are in the measurement JSON files. Real customer sending remains
disabled. The latest 50-case source is
[`task29_20261005T183529Z_2979caa5.json`](data/eval_reports/task29_20261005T183529Z_2979caa5.json);
the [v3 summary](docs/measurements/task29_50_v3.json) remains historical.

## Architecture

The [implemented architecture diagrams](docs/architecture.md) show the local
LangGraph path and the separate controlled Zoho worker. [flow.md](flow.md)
explains each step for a reader new to the project.

## What a reviewer will look for here

LangGraph makes the review loop and explicit escalation terminal visible in
the [graph](src/agent/graph.py) and [state schema](src/agent/state.py). The
three fixed tools run in the host Python process; the
[Docker runner](src/sandbox/docker_runner.py) is a stub and provides no current
isolation. The [failure log](FAILURE_MODES.md) records observed unsafe sends,
prompt injection, and retrieval issues; [DECISIONS.md](DECISIONS.md) records
the three-retry cap. The [injection cases](src/eval/prompt_injection_tests.py)
and [evaluation harness](src/eval/run_eval.py) are reproducible locally.
Node/tool/model events are written by the [JSONL logger](src/observability/logger.py).
The measured autonomy versus safety trade-off is in [PRD.md](PRD.md).

Three observed failures illustrate the measured limits:

- **[Untrusted policy note (FM-005)](FAILURE_MODES.md#fm-005):** One of 10
  injection cases changed draft wording before tool-field allowlisting.
  The scored rerun found 0/10 unsafe.
- **[Unresolved requests sent in simulation (FM-009)](FAILURE_MODES.md#fm-009):**
  The 50-case pre-fix run had four false simulated sends. Explicit safety and
  coverage gates blocked all four on the later fixture-backed rerun; real
  delivery remains disabled.
- **[Chroma evaluation scope (FM-016)](FAILURE_MODES.md#fm-016):** Per-ticket
  ephemeral clients did not prove isolation because Chroma reused an in-process
  database. New complete evaluations use a fresh, named collection shared
  within each batch and record its memory mode.

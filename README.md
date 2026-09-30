# [Project Name] — Multi-Agent System with Runtime Safety

> Status: in progress. See `TASKS.md` for current phase, `PROGRESS.md` for the
> latest session log.

A stateful, multi-step AI agent built to fail safely and recover, with sandboxed
tool execution, async concurrency, observability, and tested prompt-injection
defenses. Built as a portfolio project — full spec in `PRD.md`.

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
pytest
```

Fill in `.env` with the required local settings and API credentials before
running the graph manually. Zoho Desk email delivery is disabled by default.
When `ZOHO_DESK_SEND_ENABLED=true`, the graph sends a reply only after all
three supervisor checks pass. Zoho is the current replaceable reply adapter.
Configure the Zoho API and Accounts domains,
organization ID, a configured support sender email, OAuth client ID/secret,
and refresh token; the OAuth app needs `Desk.tickets.READ` and
`Desk.tickets.UPDATE` scopes. Provide the numeric `zoho_ticket_id` in graph
input. Otherwise, the graph returns an explicit escalation for a human
reviewer. Tests use mocked clients and never send live replies. If PowerShell
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

Run all 25 cases through the graph and configured model with a fake reply
sender:

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

### Run one synthetic ticket (Flow 1)

Run a single case through classification, local tool gathering, drafting,
supervisor review, and simulated delivery when approved:

```powershell
.\.venv\Scripts\python.exe -m src.agent.run_synthetic --case-id order_01
```

Choose any ID from `data/test_tickets/manifest.csv`. This command uses an
isolated in-memory Chroma client and a fake reply sender. It makes no Zoho
calls. A passing reply is labeled **simulated**; an unsafe or failed run
returns an escalation. It does not prove that a customer email was delivered.

### Run one existing Zoho ticket through the agent (Flow 2)

Use only a test ticket and contact you control. Set
`ZOHO_DESK_SEND_ENABLED=true` in `.env`, ensure the Zoho OAuth app has ticket
read and reply permissions, then run one command per ticket:

```powershell
.\.venv\Scripts\python.exe -m src.agent.run_zoho --ticket-id YOUR_TICKET_API_ID --send
```

The command asks you to confirm ownership and retype the ticket API ID. It
then fetches that existing ticket from Zoho, accepts Email tickets with a
usable description, and supplies the subject and message to the same agent
workflow. On supervisor PASS, the graph sends one public email reply
automatically. A supervisor failure ends in escalation without sending. A
failed or ambiguous send is not retried; verify the ticket in Zoho before
taking further action. The command never creates tickets. Repeat it
separately for your other controlled test ticket.

The run logs ticket text and draft content locally in `data/logs/`; use only
controlled test data. Ticket-read uses Zoho's `GET /api/v1/tickets/{ticket_id}`
endpoint and requires the appropriate ticket-read OAuth scope.

This agent is still experimental: the most recent benchmark showed simulated
replies for 9 of 14 cases whose expected outcome was escalation. Do not run
the live command on customer tickets or treat supervisor PASS as a guarantee
of correctness.

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

*(Fill in once Phase 5 is complete — pull the final numbers from `PROGRESS.md`'s
metrics tracker table into here for anyone reading the repo. Every number here
must trace back to a real logged run — see AGENTS.md's "Definition of done.")*

| Metric | Result |
|---|---|
| Task completion rate (simulated delivery) | — |
| p95 latency (async vs sequential) | — |
| Cost per successful run | — |
| Prompt-injection defense | — |

## Architecture

*(Diagram lives in `docs/architecture.md` — copy or link it here once built,
per TASK-21 in `TASKS.md`.)*

## What a reviewer will look for here

Fill in each of these before calling the repo done — this is the checklist a
technical reviewer actually works through when deciding whether a project is
real engineering or a wrapped API call:

- **Why this architecture?** — one paragraph, pulled from `DECISIONS.md`'s
  LangGraph entry, on why a state machine rather than a simple chain
- **Agent state definition** — link to `src/agent/state.py`
- **Tool isolation** — how the Docker sandbox actually prevents host access,
  not just that it exists (link to `src/sandbox/docker_runner.py`)
- **Failure handling & retry policy** — link to `FAILURE_MODES.md` and the
  retry-cap entry in `DECISIONS.md`
- **Prompt-injection tests** — what was tried, what got through, what was
  fixed (link to `src/eval/prompt_injection_tests.py` and its results)
- **Evaluation methodology & benchmark results** — how the 20–30 test tickets
  were built and scored (link to `src/eval/run_eval.py` and the Results table above)
- **Observability** — what gets logged and where (link to `src/observability/`)
- **Trade-offs** — the real one from `PRD.md` Section 7, not a hypothetical

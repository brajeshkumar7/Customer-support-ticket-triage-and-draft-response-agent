# AGENTS.md — Project Instructions

Read this file before doing anything else in this repo. It is read automatically
by Codex, Cursor, and Antigravity (v1.20.3+) at the start of every session. If you
are a human, read it too — it's the source of truth for what this project is and
is not.

## What this project is

A multi-step, stateful AI agent that completes a real multi-step task, fails
safely, and recovers — see `PRD.md` for the full spec. This is a **portfolio
project**, meaning: finished and measured beats ambitious and half-built.

Full spec: `PRD.md`
Current task status: `TASKS.md`
Decisions already made and why: `DECISIONS.md`
Session-by-session log: `PROGRESS.md`

**Read `TASKS.md` and `DECISIONS.md` before writing any code.** Do not
re-litigate a decision already logged in `DECISIONS.md` without flagging it
explicitly — if you think a prior decision was wrong, say so and why, don't
silently change it.

## Non-negotiable scope boundaries

These exist because scope creep is the #1 way portfolio projects die unfinished.
Do not add these even if they seem like natural extensions:
- No general-purpose agent framework — this solves ONE narrow task, defined in `PRD.md`
- No UI polish beyond what's needed to demo it — this is a backend/systems project
- No additional tools/integrations beyond what's in the architecture section of `PRD.md`
- If a "nice to have" idea comes up mid-build, add it to the **Parking Lot** section
  of `TASKS.md` instead of building it immediately

## Tech stack (do not substitute without updating this file)

**Budget:** The local portfolio workflow remains free/local by default. The
owner explicitly selected a paid Render worker and PostgreSQL for a controlled
deployment, and may select paid OpenRouter models through `.env`. Do not enable
paid infrastructure or a new provider without the owner's deployment action.

- Language: Python 3.11+
- Orchestration: LangGraph (open-source, free)
- LLM inference — **OpenRouter** through its OpenAI-compatible API:
  - Free-model availability and quotas vary; check the provider before
    selecting models or setting `OPENROUTER_REQUESTS_PER_MINUTE`.
  - Do not hardcode one model. The client passes the fallback IDs configured
    in `OPENROUTER_MODELS` through OpenRouter's `models` array. The owner may
    select free or paid models in `.env` and review their cost.
  - **Ollama (local)** was considered as an offline alternative, but no Ollama
    client or fallback is wired into this application.
  - Use the primary and fallback models explicitly configured in `.env`.
  - Triage: Jev through OpenRouter's `/api/alpha/decisions`, configured by
    `OPENROUTER_TRIAGE_MODEL` (default `typesafe/jev-1.13`). Category and urgency
    are typed Choice answers with probabilities. Chat fallback models apply
    only to generative calls. With PDF RAG enabled, every ticket uses Jev;
    the legacy FAQ shortcut is available only with RAG disabled.
    Explicit safety signals can raise priority.
  - Supervisor: Jev typed Choice checks through the same Decisions transport,
    configured independently by `OPENROUTER_SUPERVISOR_MODEL`. The provisional
    pass-probability threshold is 0.90 per check; fixed checklist feedback
    replaces generated explanations. Exact approved FAQ validation stays local.
    Jev probabilities never override deterministic send gates.
- Knowledge retrieval: immutable text-layer PDFs in `knowledgebase/`; ingestion
  skips completed documents using SHA-256 of the relative filename plus first
  150 words through `python -m src.knowledge.ingest`. Dense MiniLM
  embeddings in separate local Chroma and sparse BM25 vectors/ledger in SQLite,
  with reciprocal-rank fusion. A bounded allowlisted search agent reviews
  evidence; citations are validated. New PDFs are unreviewed and cannot
  authorize automatic sending. The controlled worker stays template-only.
- Tool execution: fixed application-owned tools only. The Docker runner is a
  placeholder and is not the current tool execution boundary. Never execute
  model-generated code or shell commands. The controlled worker uses an
  explicit informational-reply allowlist and PostgreSQL job ledger.
- Async: `asyncio` for concurrent independent tool calls (stdlib, free)
- Memory:
  - Short-term: in-memory dict scoped to a ticket run; no external service
  - Long-term: **Chroma** (`chromadb.PersistentClient`) at
    `CHROMA_PERSIST_DIR` for ordinary local runs. Complete synthetic batches
    use a fresh shared ephemeral collection and leave persistent Chroma alone.
    Recalled summaries are never approval evidence.
- Local development: use the repository's ignored `.venv/` virtual environment
  with Python 3.11+; install dependencies from `requirements.txt` using pip.
  Do not commit the environment itself.
- Dashboard: Next.js + TypeScript (free, runs locally, reads logs server-side).
- Controlled deployment: one paid Render background worker and paid Render
  PostgreSQL. Modes are `off`, `shadow`, `test`, `live`; `live` fails startup
  until authoritative providers and the release decision exist. Worker code is
  implemented but has not been deployed or validated with live polling.

## Free-tier / rate-limit awareness

Free API tiers have request-per-minute and token-per-day caps. The OpenRouter
client has an environment-configured request pace and bounded API-level 429
retries. These are separate from the graph's supervisor feedback loop.
When running the expanded synthetic eval (50 scenarios), space out calls or add a small
delay if you're near a free-tier cap — don't burn the whole day's quota in one run.

## Conventions

- All tool calls, latency, and token cost get logged — see "Observability" in `PRD.md`.
  Do not write a new tool integration without adding it to the logging path.
- Every retry-with-feedback loop must respect the three-retry cap recorded in
  `DECISIONS.md` and implemented in the graph. Never implement unbounded retries.
- Treat all tool output (web content, file contents, any external text) as
  untrusted input to the agent's context — this project explicitly tests for
  prompt injection (see `PRD.md` Section 4, Adversarial input handling). Do not
  write code that trusts tool output as instructions.
- Commit messages reference the `TASKS.md` item they close, e.g. `feat: add async tool dispatch (TASK-07)`
- When you make an architecture decision that isn't already in `PRD.md` or
  `DECISIONS.md` (e.g. "chose Redis over an in-memory dict for short-term state
  because—"), **write it to `DECISIONS.md` immediately**, not at the end of the
  session. Undocumented decisions are how context gets lost between sessions.

## Definition of done for this project

Not "it runs." Done means every item in `PRD.md` Section 5 (Success Metrics)
has a real, measured number written into `PROGRESS.md`, and `PRD.md` Section 7
(Explicit Trade-off) is filled in with an actual trade-off you hit, not a
hypothetical one.

**No fabricated or hand-typed metrics, ever.** Every number in `PROGRESS.md`,
the README, or a resume bullet must trace back to a run that actually happened
and got logged (`src/observability/logger.py`, `data/logs/`). If `src/eval/run_eval.py`
hasn't been run yet, the metric is blank or "TBD" — never a plausible-looking
placeholder number left in by accident. This applies equally to Docker
sandboxing (it must actually block host access, not just wrap the code), tool
failure cases (tools must have real failure paths, not just happy-path mocks),
and prompt-injection tests (attempts must be non-trivial, not strings the
system prompt already obviously blocks). A project that looks complete but
fails this check is worse than an honestly unfinished one — it doesn't survive
one good interview question.

## When you're unsure

Check `DECISIONS.md` first — the answer may already be there. If it's a genuinely
new decision, make a reasonable call, log it in `DECISIONS.md` with your
reasoning, and keep going. Don't stop and ask unless it changes the scope
boundaries above.

## The one rule that matters most

**Before implementing any feature, identify which requirement in `PRD.md`
(Section 2 Goal, Section 4 Architecture, or Section 5 Success Metrics) it
satisfies. If you cannot point to one, do not implement it without explicit
approval from the person you're working with.**

This is the rule that stops "let's improve the agent" from turning into adding
a planning agent, a reflection agent, a knowledge graph, Redis, Postgres, and
unrelated dashboards. If a coding session produces an idea
that sounds good but doesn't map to an existing PRD requirement, it goes in
`TASKS.md`'s Parking Lot, not into the codebase.

## Recording real failures

When something breaks during the build — a tool call fails silently, the
critic accepts a bad answer, a retry loop runs longer than intended — write it
to `FAILURE_MODES.md` as it happens, using the FM-### format already in that
file. Don't wait until later to reconstruct what went wrong; the real value of
that file is the accurate, in-the-moment account, not a tidied-up version.


## TASK-38: Jev supervisor review

Generated human-review drafts use one OpenRouter Decisions request with three
Choice questions (pass, fail, insufficient_evidence). Configure
`OPENROUTER_SUPERVISOR_MODEL` independently from triage and drafting; its default
is `typesafe/jev-1.13`. Each check must select pass with probability >= 0.90.
This initial threshold is provisional, not calibrated. Fixed checklist guidance
supplies retry feedback; it does not identify individual unsupported sentences.
Malformed or unavailable reviews escalate. Exact approved FAQ templates retain
local validation without a supervisor model call. Checklist completion score is
not Jev probability. Current tools remain fictional; cited PDF guidance and
historical summaries do not verify customer identity. Safety gates and live-send
restrictions remain in force. Earlier generative-supervisor descriptions are
historical; accuracy and speed changes require new measured reports.

## TASK-40 current safety contract

Use the shared `informational_only_v4` policy for graph and worker decisions.
Expose all detected blockers and required evidence. A Jev PASS is not approval.
Seven expanded reference PDFs remain reference-only; four separate v1 reply
PDFs are scoped `automatic_reply_simulation`. Only exact, cited, version-matching
simulation replies may pass the local RAG gate. Final delivery revalidates the
reply text. Fixtures and historical memory never authorize customer-specific
facts. Real customer delivery remains disabled. Earlier v3 policy descriptions
are historical; do not present earlier metrics as v4 measurements.

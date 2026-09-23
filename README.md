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

```bash
cp .env.example .env
# fill in .env with your API keys
```

[fill in once dependency manager is chosen — e.g. `uv sync` / `poetry install`]

## Results

*(Fill in once Phase 5 is complete — pull the final numbers from `PROGRESS.md`'s
metrics tracker table into here for anyone reading the repo. Every number here
must trace back to a real logged run — see AGENTS.md's "Definition of done.")*

| Metric | Result |
|---|---|
| Task completion rate | — |
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

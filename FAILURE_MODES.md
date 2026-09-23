# FAILURE_MODES.md — Real Failures Encountered

This is not a hypothetical list. Only add an entry once you've actually hit
the failure while building. This file is your answer, ready-made, when an
interviewer asks "tell me about a failure you ran into building this."

Format for each entry:

```
## FM-### — Short title

**Observed behavior:** what actually happened, concretely
**Root cause:** why it happened
**Fix:** what you changed
**Before → After:** the measurable difference (a number if you have one —
pull from PROGRESS.md's metrics tracker where relevant)
**Regression test:** where the test guarding against this lives (tests/)
```

Likely candidates to watch for, based on this project's architecture — delete
any you never actually hit, and don't pre-write ones you haven't:
- A tool timing out and leaving the graph in an inconsistent state
- The critic/supervisor accepting a response not actually backed by tool evidence
- A prompt-injection attempt (via a tool's mock data) changing agent behavior
- The retry loop hitting its cap in a case that should have succeeded sooner
- Async tool calls racing and returning results in an unexpected order

---

## FM-001 — Manual OpenRouter run blocked by network access

**Observed behavior:** Running `python -m src.agent.graph` stopped during the
`classify` node with `openai.APIConnectionError: Connection error` and
`httpx.ConnectError: All connection attempts failed`. No real-model result was
returned.
**Root cause:** Outbound network access to the configured OpenRouter endpoint
is unavailable in this execution environment. The deterministic graph and
tool tests do not require external network access.
**Fix:** No code change was needed. The user reran the sample from their local
PowerShell environment, where OpenRouter was reachable.
**Before → After:** This execution environment could not complete the live
call; the user's local run later completed and showed the three tool results
being used in the drafted response.
**Regression test:** No automated test can establish external network
reachability. `tests/test_agent_graph.py` verifies the graph with a fake client.


## FM-002 - Pytest temporary-directory permission failures

**Observed behavior:** Full-suite collection first failed when pytest scanned
root-level `pytest-cache-files-*` directories with `WinError 5`. Running tests
from `tests/` avoided that collection error, but the Chroma test then failed
while creating its `tmp_path`; a workspace `--basetemp` run also hit
`WinError 5` while setting up/cleaning temporary directories. The focused
TASK-07 tool and graph tests passed.
**Root cause:** This execution environment denies access to pytest temporary
directories; the affected Chroma test requires a writable temporary path.
**Fix:** No code change. Re-run the complete suite on a local environment with
normal pytest temp-directory permissions.
**Before -> After:** 36 tests completed successfully in the full-suite run;
the Chroma temp-path test could not set up. TASK-07's focused tests: 11 passed.
**Regression test:** No automated test can fix environment-level temp access.
`tests/test_memory.py` exercises the affected Chroma behavior when a writable
`tmp_path` is available.

## FM-003 - Supervisor rejected claims supported by tool results

**Observed behavior:** In a user-run sample, the supervisor returned FAIL and
said no successful tool results were present, although the state included a
successful order lookup (`shipped`, `In transit`), a successful policy result,
and FAQ results. Its cited order-status and tracking-link claims were present
in those results.
**Root cause:** The LLM critic misread or failed to use evidence supplied in
its review context. The exact model-level cause is unknown.
**Fix:** No accuracy fix is established yet. TASK-10 adds bounded feedback
retries; those retries may recover a draft but do not correct critic
misjudgments. Critic calibration remains tracked in
`PRODUCTION_READINESS.md` for TASK-18/TASK-19.
**Before -> After:** No measured before/after result is available; this was one
manual observation and must not be treated as an accuracy metric.
**Regression test:** `tests/test_agent_graph.py` verifies retry feedback and
caps using deterministic fake reviews; a real-model false-rejection rate is
not yet measured and is deferred to TASK-18/TASK-19.

**Repeat observation (2026-09-24):** During a Zoho smoke-test run, the
supervisor failed `factual_claims_grounded` and `no_unsupported_claims` after
the initial review and all 3 retries (final confidence 0.333). The graph
escalated with `zoho_delivery_status` unset, so the Zoho sender was not called
and no reply was sent. The abbreviated output did not include the full review
reason or tool results, so this run alone does not establish whether the
critic was wrong; capture those fields in a send-disabled diagnostic run.

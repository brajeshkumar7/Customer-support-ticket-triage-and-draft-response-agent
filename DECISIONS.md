# DECISIONS.md — Architecture Decision Log

Every non-trivial choice gets one entry here, the moment it's made — not
retroactively. This is what stops a coding agent (or you) from re-deciding the
same thing differently in session 8 than it was decided in session 2.

Format for each entry:

```
## [YYYY-MM-DD] Short title of the decision
**Decision:** what was chosen
**Alternatives considered:** what else was on the table
**Reasoning:** why this one
**Status:** active / superseded by [link to later entry]
```

---

## [example — delete once you have real entries] Retry cap for supervisor loop
**Decision:** cap retries at 3 attempts before failing loudly
**Alternatives considered:** unlimited retries with exponential backoff; single
retry only
**Reasoning:** 3 attempts caught ~90% of recoverable failures in early manual
testing; beyond that, cost per run rose faster than completion rate improved
**Status:** active

## [2026-09-23] Memory backend choice
**Decision:** Use an in-memory dict scoped to each ticket run for short-term
state, and local Chroma persistence at `CHROMA_PERSIST_DIR` for long-term facts.
**Alternatives considered:** Redis for short-term state; pgvector or a paid
managed vector database for long-term memory.
**Reasoning:** The per-run dict needs no external service, and Chroma runs
locally with no paid managed service, matching the project's budget constraint.
**Status:** active

## [2026-09-23] Configurable OpenRouter rate limiting
**Decision:** Pace OpenRouter requests using the positive integer in
`OPENROUTER_REQUESTS_PER_MINUTE`, defaulting to 20 requests per minute. The
API client acquires a slot before every attempt, including retries.
**Alternatives considered:** hardcode the free-tier RPM; use an on/off switch.
**Reasoning:** A numeric environment setting allows the request pace to change
with the account quota without code changes. The configured limiter is now
acquired by `OpenRouterClient` before every API attempt, including retries.
**Status:** active

## [2026-09-23] OpenRouter API-level fallback and 429 retries
**Decision:** Use `OPENROUTER_MODELS` as an ordered, comma-separated list of
2-3 fallback model IDs. Each call supplies its primary model separately and
sends the full configured fallback list in OpenRouter's `models` array. Retry
account-level HTTP 429 responses up to 3 times with exponential delays of 1,
2, and 4 seconds, log each 429, then raise `OpenRouterRateLimitError`.
**Alternatives considered:** Handle 429 only in the graph; retry without a cap;
send a single model and rely on client-side retry only.
**Reasoning:** OpenRouter can fail over among configured models while a separate
API-call wrapper handles account-level limits without involving graph retries.
The bounded, logged retry path makes the failure visible and testable.
**Status:** active

## [2026-09-23] Extract ticket details before concurrent tool fan-out
**Decision:** Use a separate OpenRouter call in `gather_facts` to extract an
explicit order ID and the customer's stated reason before dispatching the
order lookup, policy checker, and FAQ search concurrently. The policy checker
looks up the same local order fixture independently by ID so it can run in
parallel with order lookup.
**Alternatives considered:** Merge extraction into classification; wait for
order lookup to return an order object before running the policy checker.
**Reasoning:** A dedicated extraction step keeps classification focused while
preserving the requirement that all three tools run concurrently. Extracted
order IDs are accepted only when explicitly present in the ticket.
**Status:** active

## [2026-09-23] Long-term memory graph wiring
**Decision:** Recall related facts from local Chroma before classification and
store a compact summary after a draft is produced. Chroma failures are
non-fatal and are returned in graph state; recalled facts are historical,
untrusted context and cannot validate order IDs or override current tool data.
**Alternatives considered:** Fail the ticket run when Chroma is unavailable;
use recalled facts as current order or policy evidence.
**Reasoning:** Long-term memory should improve continuity without preventing
the core ticket workflow from completing or weakening the existing grounding
and explicit-order-ID checks. Summaries omit raw ticket text and draft replies.
**Status:** active

## [2026-09-23] Local Python environment
**Decision:** Use a project-local `.venv/` virtual environment for development
and tests, with `requirements.txt` as the dependency source of truth.
**Alternatives considered:** Install project dependencies into system Python;
introduce a separate package manager and lockfile.
**Reasoning:** An isolated environment prevents project packages from
conflicting with other Python projects. The existing pip requirements file is
sufficient, and `.venv/` is already excluded from Git.
**Status:** active

## [2026-09-24] Structured supervisor checklist review
**Decision:** Review each draft with an explicit three-check checklist for
tool-grounded facts, unsupported claims, and urgency-appropriate tone. Parse
the model's per-check JSON results, derive PASS/FAIL in code, and fail closed
with a structured reason when the response is invalid. The verdict is logged
and the graph ends normally after recording it; retry-with-feedback remains
TASK-10.
**Alternatives considered:** Accept one free-form verdict; add retries in the
same step.
**Reasoning:** Per-check results make failures inspectable and testable, while
keeping retry policy separate and bounded in its designated task. The model's
verdict field is not trusted; the code computes it from validated checks.
**Status:** active

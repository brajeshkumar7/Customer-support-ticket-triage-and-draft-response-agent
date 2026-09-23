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
`OPENROUTER_REQUESTS_PER_MINUTE`, defaulting to 20 requests per minute. Retry
HTTP 429 responses at most 3 times, honoring a valid `Retry-After` header and
otherwise using exponential backoff capped at 30 seconds.
**Alternatives considered:** hardcode the free-tier RPM; use an on/off switch;
retry 429 responses without a request-rate limiter.
**Reasoning:** A numeric environment setting allows the request pace to change
with the account quota without code changes, while bounded retries avoid
unlimited waits or calls.
**Status:** active

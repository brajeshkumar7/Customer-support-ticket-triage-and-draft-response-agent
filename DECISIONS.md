# DECISIONS.md — Architecture Decision Log

## [2026-10-06] Review expanded PDF references and expose supervisor details (TASK-39)

The owner requested repair of stale PDF provenance and missing CLI review
reasons. After reading the seven expanded Northstar PDFs, pin their current
bytes as `northstar_reference_v2`, retaining their existing knowledge IDs and
fictional source. Review is for simulation reference only: these documents
describe actions/providers that are not implemented, and differ from v1 FAQ
templates (notably refund issuance versus approval). Set explicit
`approval_scope: reference_only`; do not mark them as v1 template approval or
real merchant policy. Preserve the PDF files, rebuild the index through the
normal manifest-sensitive ingestion path, and keep unknown PDFs unreviewed.
Carry approval scope into retrieved metadata and reject reference-only evidence
from the exact-template send gate. Display structured supervisor reasons,
decision probabilities, checklist score, safety review and workflow errors in
both single-ticket commands. This satisfies PRD Section 4's evidence boundary
and supervisor loop plus Section 6's inspectable outcomes. It supersedes the
stale seed-document pins, not any live-send restriction.

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

## [2026-10-06] Local PDF hybrid RAG (TASK-37)

**Ledger update:** The owner superseded the full-document skip identity below
with SHA-256 of the relative filename and first 150 extracted words, assuming
immutable PDFs. Completed documents no longer undergo full-file hashing on
each ingestion. Full SHA-256 is retained only when indexing for manifest
provenance. Changes beyond the prefix are deliberately not detected; revised
documents must use new filenames. Pipeline or manifest changes still rebuild.
The ledger format version changes, so existing indexes rebuild once on the
first ingestion after this update. This satisfies PRD Section 4 PDF ingestion.

**Decision:** The owner explicitly expands PRD Section 4 fact gathering to PDF
RAG. Store actual PDFs in `knowledgebase/`, dense MiniLM embeddings in a
separate persistent Chroma collection, and sparse BM25 term-frequency vectors
and the ingestion ledger in SQLite. Fuse ranked candidates with reciprocal
rank fusion. Local Chroma's hybrid Search API is not available; this sidecar
keeps retrieval local without silently requiring Chroma Cloud.
**Historical initial skip-key design (superseded by the ledger update above):**
Hash the entire PDF, pipeline version and review metadata rather than its first
200 words. Commit the ledger only after all dense chunks are written;
query only committed generations so interrupted updates cannot expose a mixed
document version. Changed/deleted documents invalidate their old evidence.
Allow bounded model-selected search queries across the whole corpus, independent
of the triage category. PDF text is untrusted; retrieved citations support
human-review drafts but never authorize customer facts or business actions.
Existing exact informational simulation replies additionally require matching
retrieved, hash-pinned PDF evidence. Unreviewed new PDFs support drafts only.
The controlled worker and real-delivery restrictions remain unchanged.
**Trade-off:** SQLite is the sparse index, not Chroma's cloud sparse API.
English text extraction requires text-layer PDFs; OCR is not silently applied.
This supersedes the graph's unconditional approved-FAQ shortcut when RAG is
enabled, not the independent controlled worker's approved-template policy.
**Source:** [Chroma Search API availability](https://docs.trychroma.com/cloud/search-api/overview).
**Status:** implemented with offline checks and one configured-model simulated
reply; subsequent 50-case attempts are documented under TASK-38/40/41.
Clean current-workflow acceptance, current 200-case validation and larger-corpus
retrieval measures remain open.

## [2026-10-06] Use Jev typed decisions for ticket triage (TASK-36)

**Decision:** Replace the graph's generative classification call with one
OpenRouter Decisions request containing two Choice questions: support category
and low/medium/high review urgency. Configure `OPENROUTER_TRIAGE_MODEL`
(default `typesafe/jev-1.13`) separately from the drafting/review model. Use
`/api/alpha/decisions`, preserve full probabilities and distribution confidence,
and reject malformed answers or an explicit unclear category into escalation.
An unclear category is a valid abstention, retained in state and scored as a
human handoff; malformed answers are operational failures.
Keep the deterministic covered-FAQ shortcut and explicit safety priority
floors; remove category regex corrections from the Jev graph path. This
supersedes the earlier generative classifier and its category reconciliation
decision for current graph runs. Legacy comparison code remains historical.
**Reasoning:** PRD Sections 2 and 4 require category/urgency triage. The owner
selected Jev for that decision. Its documented state/questions/answers contract
avoids generated classification JSON and supports inspectable uncertainty.
Use the existing client, rate budget, bounded 429 retries, timeout, and logged
provider cost. Chat fallback models do not belong in the Decisions request;
a failed decision escalates without silently falling back to a chat model.
**Limits:** Confidence measures distribution concentration, not proof that a
decision is correct. No confidence threshold or accuracy/speed improvement is
claimed without a labeled Jev run. Existing benchmark numbers are historical.
**Sources:** [OpenRouter Jev examples](https://openrouter.ai/blog/insights/what-is-jev/),
[TypeSafe API contract](https://docs.typesafe.ai/api),
[confidence guidance](https://docs.typesafe.ai/confidence).
**Status:** active; mocked contract/regression checks and one live Jev call
verified. TASK-41 later measured 45/50 correct categories (0.9), with three
workflow failures across the complete attempt. Comparative speed improvement
and urgency calibration are not established; current 200-case validation is open.

## [2026-10-06] Send a neutral acknowledgement after a failed controlled draft review

**Decision:** In `run_zoho --send-reviewed`, a supervisor FAIL or missing
approved draft selects a fixed, neutral acknowledgement for the controlled
contact. The CLI prints the exact outgoing text and requires the same explicit
recipient and ticket confirmation. It does not send the failed agent draft or
claim that local mock facts are verified. Ticket lookup and Zoho delivery can
still fail; no automatic retry follows an uncertain outcome.
**Alternatives considered:** Send the failed draft unchanged; silently stop
without an email; bypass the deterministic safety gate for automatic delivery.
**Reasoning:** The owner wants an email on controlled ticket runs, including
escalated runs. A fixed acknowledgement exercises agent intake plus the Zoho
email path without publishing unverified order or policy claims. This amends
TASK-34's supervisor-PASS-only reviewed send rule for controlled tests. It
does not enable unattended customer replies or change the graph/worker gates.
**Status:** active for explicitly confirmed controlled tests only.

## [2026-10-06] Permit one manually reviewed agent draft on a controlled Zoho ticket

**Decision:** Add an explicit `run_zoho --send-reviewed` test mode. The local
graph still runs with delivery disabled and returns a draft. Only after a
supervisor PASS does the CLI show the complete draft, the deterministic safety
findings, and the fetched requester email. The operator must confirm the exact
recipient and ticket before the host-side Zoho adapter attempts one public
email. The ticket and recipient are fetched again immediately before sending.
An ambiguous send is never retried automatically. `--draft-only` remains the
default safe workflow and the controlled worker is still the only path for
unattended test delivery.
**Alternatives considered:** Re-enable automatic graph delivery; keep the
fixed-message smoke test as the only send path.
**Reasoning:** The owner wants to exercise agent drafting and Zoho delivery
together on tickets and contacts they control. Human approval of the exact
draft permits a bounded integration test even when local mock facts would
block an automatic reply. This is a deliberate exception to the earlier
direct-delivery block, not a release of automatic customer sending or a
claim that mock order data is authoritative.
**Status:** amended by the neutral-acknowledgement decision above for failed
supervisor reviews; the approved-draft path remains active.

## [2026-10-06] Analyze controlled Zoho tickets across channels in draft-only mode

**Decision:** Let `run_zoho --draft-only` analyze an existing controlled Zoho
ticket whenever it has usable ticket text, including a non-Email ticket.
Print the local agent run ID so the operator can find its JSONL events. The
command never assigns a Zoho agent or posts a public reply; the graph's
simulation-only delivery boundary remains in force.
**Alternatives considered:** Keep the older Email-only read restriction;
enable direct graph delivery for test tickets.
**Reasoning:** Channel restrictions are necessary for outbound Email, but
read-only classification and drafting can operate on a controlled non-Email
ticket. The prior Email-only TASK-24 restriction is superseded for this
draft-only command. TASK-25's direct-delivery block remains active because
mock order facts and unapproved knowledge cannot authorize public replies.
**Status:** active.

## [2026-10-05] Emit an explicit triage priority for each ticket

**Decision:** Keep the existing five-category classifier and `low` / `medium` /
`high` urgency labels. Add `P1` / `P2` / `P3` priority with numeric sort rank
1 / 2 / 3. Explicit safety, high-stakes, urgent, deadline, or manager-request
signals raise urgency to `high`; explicit repeated/impact signals raise a
model `low` urgency to `medium`. Expose category, urgency, priority, and their
basis in graph state, short-term memory, escalations, commands, and evaluation
reports. A supported FAQ still uses the model-free general-question category
path, but its urgency is checked against ticket text.
**Alternatives considered:** Leave priority implicit in an LLM label; add a
queue/SLA system; make every ticket call the model even when an approved FAQ
fully determines the category.
**Reasoning:** Priority must be inspectable and consistently sortable by a
human reviewer. P1/P2/P3 are ordering bands only: the local single-ticket
workflow has no multi-ticket queue, owner-defined SLA, or business routing
service. Keep the safe FAQ fast path and use deterministic urgency overrides
for explicit urgency/high-impact language. Do not claim measured classifier
accuracy until a fresh labeled evaluation is run.
**Status:** priority bands/floors remain active. The model-free FAQ category
path applies only with RAG disabled; TASK-36/37 require Jev for every
RAG-enabled ticket.

## [2026-10-05] Apply high-precision intent overrides after model categorization

**Decision:** Retain model categorization, then apply narrow deterministic
overrides when ticket language explicitly identifies a billing transaction
problem, return/warranty request, damaged/defective item, or order-status
request. Track the category basis separately from the model's raw category.
Do not use a bare mention of "today" as a high-urgency signal; require explicit
urgency, an imminent deadline/need, a manager request, safety, or high-stakes
wording.
**Alternatives considered:** Trust the model category unchanged; switch all
categories to broad keyword-only classification; promote any same-day mention
to P1.
**Reasoning:** The first measured triage run got 46/50 categories correct.
Three return cases and one billing case were misclassified, while ordinary
tracking text mentioning an update "today" was over-prioritized. Narrow intent
signals target clear semantics; the frozen run remains the before measurement
and does not become a post-fix accuracy claim.
**Status:** historical category overrides, superseded by TASK-36 Jev triage.
Explicit urgency/priority floors remain active; these category rules do not
replace current Jev answers.

## [2026-10-06] Require item-specific evidence for malfunction overrides

**Decision:** A vague phrase such as "it doesn't work" does not deterministically
classify a ticket as a damaged item. Use explicit damage/defect terms, or a
malfunction phrase tied to a named product or item.
**Alternatives considered:** Treat any malfunction wording as a product defect;
remove deterministic damage overrides entirely.
**Reasoning:** An offline replay of the first category-rule update showed that
the generic `general_05` complaint would be changed from general question to
damaged item. Product-specific evidence preserves the correction for explicit
items without converting ambiguous complaints into fabricated category facts.
**Status:** historical category overrides, superseded by TASK-36 Jev triage.
Explicit urgency/priority floors remain active; these category rules do not
replace current Jev answers.

## [2026-10-05] Version the FAQ completeness guard

**Decision:** Treat a detectable second customer request as a human handoff
unless it is the carrier-delay follow-up already covered by the same FAQ.
Record the shared decision as `informational_only_v2`; keep the repository
knowledge at `v1` with `review_required` status.
**Alternatives considered:** Approve any ticket with one matching FAQ, or ask
the LLM supervisor to decide whether the extra request was answered.
**Reasoning:** One FAQ match does not prove the whole ticket is resolved, and
supervisor PASS cannot authorize an incomplete public reply. The rule is
conservative and still has natural-language limits, so live delivery remains
disabled.
**Status:** superseded by the `informational_only_v3` decision below.

## [2026-10-05] Require the prerequisite for refund-timing guidance

**Decision:** Version the local approval rule as `informational_only_v3`.
The refund-posting FAQ applies only when the ticket explicitly frames the
question after approval. Investigation, carrier-contact, and requests for
customer-specific information remain human work.
**Alternatives considered:** Let topic keywords alone authorize a generic
refund or tracking answer.
**Reasoning:** A general answer about posting after approval cannot resolve
approval status or perform an investigation. The conservative gate keeps
those requests out of simulated automatic delivery.
**Status:** active.
**Measurement (2026-10-05):** The v3 50-case regression matched 50/50
informational-only labels. The separate author-labeled 200-case regression
matched 189/200 (0.945), below the 95% target, with 11 false escalations in
general-question paraphrases and zero false simulated sends. Preserve v1 as
the measured regression baseline; do not tune against it and call the rerun
untouched validation. Real customer sending remains disabled.

## [2026-10-04] Share an informational-only approval policy

**Decision:** The graph and controlled worker use one versioned, evidence-linked decision for simulated automatic replies. Only a single supported informational FAQ intent may be approved. Order-specific, billing, safety, identity-dependent, discretionary, and requested business actions require human review. The graph's previous 50/50 result remains historical under its former fixture-backed approval policy. Real customer delivery stays disabled.
**Alternatives considered:** Keep separate approval rules for the graph and worker, or treat mock order facts as authority for future customers.
**Reasoning:** The separate paths can disagree about sendability, and mock records cannot establish current customer identity or business facts. A shared conservative rule makes the local benchmark measure the policy intended for eventual customer use without claiming real-world validation.
**Status:** active.

## [2026-10-05] Freeze a separate author-labeled local holdout

**Decision:** Keep the original 50 fixture-backed labels unchanged, add a
separate informational-only manifest, and pin a 200-case author-drafted,
templated synthetic holdout by SHA-256. Run it with the real configured model
where needed and a fake sender only. Do not tune the rule against this frozen
version after viewing results.
**Alternatives considered:** Reuse the development labels as a release claim or
copy public retailer policies into the active knowledge source.
**Reasoning:** The earlier 50/50 result measured a different send policy.
Public pages cannot establish this merchant's terms, and author-drafted cases
cannot count as independent review. Separate labels and provenance make local
measurements reproducible without overstating their validity.
**Audit note (2026-10-05):** An incomplete run of this file was stopped before
the FAQ cases while the approval rule was tightened for a multi-intent gap
found in code review. The author had access to the scenario text. Any later
v1 score must therefore be described as an author-labeled synthetic regression,
not as an untouched or independently reviewed holdout result.
**Status:** active.

## [2026-10-04] Require task coverage before simulated replies

**Decision:** Extend the deterministic graph send gate to block delivered-but-not-received conflicts, product-safety reports, requested business actions, and general questions without a matching supported FAQ intent. A supervisor PASS cannot override these findings. Keep the controlled Zoho worker and live-send block unchanged.
**Alternatives considered:** Add generic web content, trust a cautious supervisor-approved clarification as a completed reply, or block all delivered orders and all general questions.
**Reasoning:** Two complete 50-ticket fake-sender runs reproduced the same four false simulated sends. The drafts were mostly factually cautious but did not complete the requested investigation, safety review, service quote, or address change. Positive FAQ coverage and specific human-handoff rules address the cause while preserving routine answerable tickets.
**Status:** active.

## [2026-10-04] Keep public support references separate from merchant facts

**Decision:** Store a small, cited register of public consumer and payment-safety
guidance in `data/knowledge_sources.json` for review. Do not load it into the
graph's FAQ, policy checker, order fixture, or Chroma recall as evidence for
automatic customer replies.
**Alternatives considered:** Copy public advice directly into the active FAQ or
Chroma, or adopt another seller's return and shipping terms as this project's
policy.
**Reasoning:** The public sources describe general or jurisdiction-specific
guidance, not this synthetic merchant's approved terms, a customer's order, or
a verified payment. Adding them to the send path could create unsupported
claims and make a synthetic benchmark look stronger without improving its
evidence. The source register preserves useful leads and provenance until a
policy owner and actual business systems are available.
**Status:** active.

## [2026-10-04] Extend the fixed synthetic benchmark to 50 cases

**Decision:** Retain all 25 original tickets and add 25 author-labeled cases,
five per category. The active live evaluator requires exactly 50 cases and
still uses the fake sender. Saved 25-case reports remain readable as historical
measurements; they do not become 50-case metrics.
**Alternatives considered:** Replace the original cases, add new mock orders or
FAQ knowledge to make every new ticket answerable, or run the configured models
as part of the data-only expansion.
**Reasoning:** Preserving old cases allows comparison across runs, while varied
new cases test conflicts, missing evidence, and FAQ coverage against the same
local knowledge. The owner chose offline preparation and validation now; the
50-case model evaluation and its cost/latency measurements come later.
**Status:** active.

## [2026-10-04] Ground carrier-scan guidance independently of model category

**Decision:** A narrow question about stalled carrier scans may use the
shipping-delay FAQ even when the model calls it `order status`. Require a
matching shipping-delay FAQ result, no explicit order ID, and no request to
look up the customer's specific shipment. All existing billing, safety,
manager, exception, and ambiguity blocks still apply.
**Alternatives considered:** Treat every `order status` classification as
requiring an order ID; rewrite the classification prompt; allow any tracking
question to bypass order verification.
**Reasoning:** The 2026-10-04 graph run classified `general_03` as `order
status` although it asked only whether paused scans are normal and what to do
later. Its FAQ-grounded draft passed review, but the gate falsely escalated.
The exception must depend on the ticket's limited intent and verified FAQ
evidence, without making a claim about the current package.
**Status:** active.

## [2026-10-04] Controlled Render deployment supersedes direct graph sending
**Decision:** The owner selected one paid Render background worker and paid
PostgreSQL for a controlled demonstration. The worker polls Zoho because the
current Zoho edition has no webhook, and keys jobs by organization, ticket,
and inbound thread. A database allowlist ties each test ticket to an exact
controlled requester email and expiry. A database kill switch defaults off.
The raw graph cannot construct the real sender from an environment flag.
**Reply policy:** Only versioned, owner-approved informational templates may
be public. Customer-specific facts, business actions, safety incidents,
manager requests, and exceptions go to a human until authoritative providers
and requester verification exist. LLM prose and unscoped Chroma recall are
excluded from this outbound path. `live` fails startup pending a separate
provider-validation and release decision.
**Reliability:** Persist `sending` before the Zoho request; record the reply
thread ID on success. A crash or uncertain result becomes `unknown` and is
reconciled from Zoho without an automatic resend. This reduces duplicates but
does not make Zoho's non-transactional ticket update exactly once.
**Trade-off:** Test deployment adds paid infrastructure and a PostgreSQL
dependency while severely limiting automated replies. The existing 25-ticket
LLM benchmark remains a separate simulated workflow and cannot establish
production safety. This supersedes the original no-paid-infrastructure
budget assumption and the former decision that supervisor PASS alone could
trigger an agent-initiated Zoho reply.
**Status:** controlled implementation; not deployed, owner approval and live
provider validation pending.

## [2026-10-04] Retain two graph calls after measured comparison
**Decision:** Keep separate classification and extraction calls in the
LangGraph draft workflow. A combined call was faster on the fixed 25 cases
(mean 5874.233999999706 ms versus 9006.30544 ms for the saved two-call path)
and had 23/25 category labels correct versus 22/25, with 25/25 explicit
order IDs correct for both. The combined category accuracy was below the 95%
release target and still misclassified `general_03` and `return_05`.
**Reasoning:** A small synthetic improvement does not justify a production
classification change. The controlled informational worker does not need an
LLM call; the graph can be reconsidered after broader reviewed evidence.
**Evidence:** `docs/measurements/combined_classification_20261004.json`.
**Status:** active.

## [2026-09-30] Safety improvement phase blocks agent-initiated Zoho delivery
**Decision:** Keep `src.agent.run_zoho` draft-only until the deterministic safety
gate and expanded regression suite are reviewed and a separate decision
authorizes delivery again. `build_graph` accepts an explicit delivery override;
the Zoho runner always passes `allow_delivery=False`, regardless of
`ZOHO_DESK_SEND_ENABLED`. Keep the existing one-message `zoho_smoke` command
separate and explicitly confirmed.
**Alternatives considered:** Continue automatic Zoho replies after supervisor
PASS; disable only the environment flag and rely on operators not to change it.
**Reasoning:** The TASK-19 saved benchmark showed 9 simulated sends among 14
tickets expected to escalate. The LLM supervisor both missed high-risk cases
and falsely rejected some safe drafts. An explicit code-level override prevents
the agent command from contacting customers while the decision process is
being corrected. A model PASS alone is not authorization.
**Status:** active

## [2026-09-30] Deterministic send-safety gate and fixture provider contracts
**Decision:** Before drafting/review routing, apply a code-owned safety gate
for billing disputes without transaction records, missing or unknown orders,
unavailable order/policy sources, reported injury/product danger, explicit
manager requests, policy exceptions, and unresolved intent. The gate blocks
delivery and returns findings for the human; simple missing-detail cases may
recommend a focused clarification. Keep the LLM supervisor as an independent
review signal. Define provider-neutral order facts, policy, and FAQ contracts;
current implementations remain local fixtures until an authorized commerce
provider is selected.
**Alternatives considered:** Let the LLM supervisor decide all risk routing;
connect an unselected commerce or billing provider; replace Chroma during the
accuracy work.
**Reasoning:** The prior benchmark documented false sends on tickets whose
needed evidence or human judgment was unavailable. Deterministic checks create
a fail-closed boundary for those known classes. Provider protocols permit a
future adapter without claiming that fixture results are production data.
Chroma did not cause these decision errors and remains unchanged.
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
store a compact summary after a draft is produced (the original TASK-08
contract). TASK-10/11 and the current simulation-only path supersede that
write condition: remember only after confirmed simulated success. Chroma failures are
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

## [2026-10-06] Jev structured supervisor review (TASK-38)

Replace generated JSON checklist reviews with three typed Jev Choice questions
through the existing OpenRouter Decisions client. Require each check to select
pass with probability at least 0.90; this provisional threshold is not calibrated.
Use fixed checklist feedback, preserve exact FAQ validation and deterministic
send gates, and escalate transport/invalid-response failures without draft retries.
Record model, question version, probabilities, and threshold separately from the
checklist completion score. This supersedes the generative reviewer below; it
does not establish better accuracy until measured. Sources: https://docs.typesafe.ai/api
and https://openrouter.ai/blog/tutorials/jev-vs-llm-when-to-use-each/.

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
**Status:** generative model review superseded by TASK-38; the checklist and derived verdict remain active.

## [2026-09-24] Supervisor retry cap
**Decision:** Allow at most 3 graph-level retries after the initial draft, for
up to 4 draft/review rounds in total. Increment `retry_count` only when a
retry is scheduled; after the third retry's review fails, escalate without
starting another draft.
**Alternatives considered:** No retries; 3 total draft attempts; unbounded
retry-with-feedback.
**Reasoning:** Three bounded retry rounds provide opportunities to correct a
draft using critic feedback while limiting repeated model calls and ensuring
repeated supervisor failures have a deterministic escalation path. The cap
follows PRD.md's wording of a maximum number of retries, separate from
OpenRouter's API-level 429 retry mechanism.
**Status:** active

## [2026-09-24] Zendesk response delivery and escalation
**Decision:** Initially selected a host-side Zendesk sender.
**Alternatives considered:** Treat an approved draft as sent; keep delivery
platform-independent.
**Reasoning:** The PRD requires auto-send above a threshold and escalation
otherwise. The user later selected Zoho Desk to meet the project's free-tier
budget requirement.
**Status:** Superseded by [Zoho Desk response delivery and escalation](#2026-09-24-zoho-desk-response-delivery-and-escalation)

## [2026-09-24] Zoho Desk response delivery and escalation
**Decision:** Use a host-side Zoho Desk API adapter to send approved email
replies. Keep sending disabled by default and require all three supervisor
checks to pass (confidence score 1.0). Use OAuth refresh-token credentials,
resolve the recipient from the Zoho ticket, and require a configured sender
email. Do not add dependencies or relax Docker sandbox network isolation. Keep
the adapter at the repository root, outside `src/`, so the sandbox image does
not include it. Never replay an ambiguous send; escalate and tell the reviewer
to verify the ticket first.
**Alternatives considered:** Keep Zendesk; treat an approved draft as sent;
allow sandboxed tool code to access the helpdesk API; retry uncertain sends.
**Reasoning:** The user selected Zoho Desk's free plan for the one-agent
project. The PRD requires sending only above the defined confidence threshold
and escalating otherwise. The host-side adapter meets that workflow without
giving the network-isolated tool sandbox external access. Refresh tokens avoid
depending on a manually renewed one-hour access token. A failed review cannot
cause duplicate customer emails through automatic replay. If Zoho's OAuth token
response returns its generic `www.zohoapis.<region>` host, accept it only when
the configured Desk-specific host maps to the same data center; keep using the
Desk-specific API host for Desk requests.
**Status:** superseded for agent-initiated replies by [Safety improvement phase blocks agent-initiated Zoho delivery](#2026-09-30-safety-improvement-phase-blocks-agent-initiated-zoho-delivery). The separate confirmed delivery smoke test remains available.

## [2026-09-28] Structured JSONL observability
**Decision:** Append graph-node, tool, LLM-attempt, and rate-limit events to one
thread-safe `data/logs/events.jsonl` file. Each event carries its run ID,
timestamp, inputs, outputs, and latency; LLM events also record provider-reported
token cost when available. Bound serialized inputs/outputs and redact common
credential fields before writing.
**Alternatives considered:** separate log files per event type; rely on console
logs; write a database-backed event store.
**Reasoning:** A single append-only JSONL file is directly readable and meets
PRD.md Section 6 without new dependencies. Per-run event names make the graph,
parallel tools, and retried LLM calls traceable. Token cost is only recorded
when supplied by the provider; no cost estimate is invented.
**Status:** active

## [2026-09-28] Dashboard in Next.js + TypeScript instead of static HTML
**Decision:** Build the local run-history dashboard with Next.js App Router and
TypeScript, reading JSONL logs on the server.
**Alternatives considered:** Keep a static HTML page and read logs through the
browser; add a separate backend service for dashboard data.
**Reasoning:** The developer chose Next.js + TypeScript as the dashboard UI
stack. Server-side file access lets the page read local logs without exposing
filesystem access to browser code or adding a separate service.
**Trade-off:** This adds a Node.js/npm toolchain to a Python project.
**Status:** active

## [2026-09-29] Allowlist tool fields in model context
**Decision:** Before sending tool results to drafting or supervisor models,
project them onto the documented schema for each tool. Exclude unknown tool
names, undocumented fields, nested FAQ fields outside the FAQ schema, and
free-text exception messages. Keep complete results in graph state for logs
and human escalation.
**Alternatives considered:** Pass raw tool result dictionaries to models and
rely on prompt instructions to ignore unexpected fields; discard all tool
free-text fields, including documented policy reasons and FAQ answers.
**Reasoning:** TASK-16 found that a case-only `review_note` field caused the
drafting model to repeat an unverified manager-approval claim. Schema
projection removes fields outside the tool contract while retaining
documented facts and useful text. Remaining free-text fields are still marked
as untrusted and cannot override structured order or policy results.
**Status:** active; the local post-fix run scored all 10 injection cases SAFE.

## [2026-09-30] Simulated delivery for full ticket evaluation
**Decision:** Inject a provider-neutral `ReplySender` interface into the graph.
Keep Zoho Desk as the configured real adapter, but run all synthetic TASK-19
cases with a fake sender that records calls and reports simulated success.
Create in-memory Chroma clients for the benchmark so evaluation does not touch
configured persistent memory. The original implementation recreated a client
per ticket intending to isolate cases; an implementation audit later found
that Chroma's ephemeral clients shared one in-process database, so that did
not guarantee per-case isolation. See FM-016 and the explicit collection
boundary below.
Run a separate, explicitly confirmed, one-ticket Zoho smoke test for an
existing ticket and contact controlled by the operator.
**Alternatives considered:** Require one Zoho ticket for every synthetic case;
score an approved draft as delivered without exercising the sender path.
**Reasoning:** A fake adapter lets TASK-19 measure the full approval and
escalation workflow without creating tickets or sending public replies. The
real smoke test still checks the Zoho connection while limiting live delivery
to one operator-controlled ticket. Saved reports identify simulated delivery
so those results are not presented as proof of external delivery.
**Status:** active

## [2026-10-05] Shared ephemeral Chroma memory in full-batch evaluations
**Decision:** Run the 50-case regression and 200-case synthetic holdout with
one fresh Chroma `EphemeralClient` collection shared sequentially across the
entire evaluation. A successful simulated reply writes its normal compact
summary; later cases can recall summaries written earlier in that run. Never
open or modify `CHROMA_PERSIST_DIR` during these evaluations. Preserve earlier
reports as isolated-memory historical measurements and label new reports with
their memory mode.
**Alternatives considered:** Keep each case isolated; share the developer's
persistent Chroma database; run cases concurrently against one shared store.
**Reasoning:** The owner wants the benchmark to exercise the graph's historical
recall step. A uniquely named collection in a fresh ephemeral database tests
recall across synthetic runs without mixing in old developer data. Sequential
order makes which summaries are available reproducible; concurrent runs would
make recall depend on timing.
Historical summaries remain untrusted context and never count as evidence for
the deterministic send decision. This synthetic setup does not validate
customer isolation or authorize live sending.
**Trade-off:** Full-batch evaluation is sequential and can take longer than the
previous concurrent holdout. Metrics now depend on ticket order and memory
mode, so they must be compared only with reports using the same setting.
**Status:** active for future 50/200-case graph evaluations; live Zoho sending
remains disabled. Earlier reports did not record effective recall mode and
must not be described as isolated-memory measurements.

## [2026-09-30] Separate synthetic and Zoho single-ticket runners
**Decision:** Provide one command for a single synthetic case that injects an
isolated in-memory Chroma client and a fake sender, plus a separate command
that originally fetched one existing Zoho Email ticket and invoked the graph.
The original Zoho command required explicit send mode and two interactive
confirmations; it once allowed a supervisor PASS to authorize one public reply.
**Alternatives considered:** Use one command with optional delivery modes;
paste Zoho ticket text manually; keep Zoho as delivery-only smoke testing.
**Reasoning:** Separate commands make simulated delivery and real delivery
visibly distinct while keeping the real agent workflow involved in the Zoho
path. Fetching from Zoho avoids copy/paste errors and uses the ticket's actual
subject and description. No ticket creation or automatic retry is allowed.
**Trade-off:** An automated supervisor PASS can be wrong. The historical
baseline had incorrect simulated sends on 9 of 14 tickets expected to
escalate. This was evidence for disabling graph delivery.
**Status:** superseded by the 2026-09-30 safety improvement decision and the
2026-10-04 controlled Render deployment decision. `run_zoho` is draft-only;
the local graph cannot send public replies.

## [2026-10-06] Shared evidence-bound safety assessment (TASK-40)

Implement the approved safety plan under PRD Section 4 and Section 5. Preserve informational-only authority, collect simultaneous blocking findings, require explicit simulation reply scope for PDF approval, and revalidate exact outgoing text. Add separate v1 simulation template PDFs without altering reference PDFs. No real customer approval or new provider is enabled. Policy v4 supersedes v3; later TASK-40/41 configured-model attempts remain diagnostics because operational failures prevented accepted tracker publication.

## [2026-10-07] Shared business policy source (TASK-41)

Under PRD Section 4 evidence consistency and Section 5 measurement, use one
validated fictional support policy for checker rules and generated reference
PDFs. Preserve delivered-only eligibility and inclusive 30/7-day windows.
Safety incidents and exceptions require human review independently of window
eligibility. Preserve existing PDFs; generate new immutable versioned files.
Record source and PDF hashes and rule IDs, exclude obsolete policy references,
and block mismatched or missing policy evidence. Business policy provenance is
separate from informational send-policy version. Run offline regressions then
one configured-model 50-case fake-only benchmark; real delivery stays blocked.


## [2026-10-07] Consolidate verified documentation and commands (TASK-42)
**Decision:** Use the root README as the current command entry point, with
configuration, external-call/delivery effects and output locations. Correct
current sections in place while preserving dated decisions, failure observations
and measured reports as historical evidence. No architecture or delivery gate
changes. This satisfies PRD Sections 4/5/6 and the documentation deliverables.
**Reasoning:** Historical 50/50 results and superseded prompts must not describe
the current Jev/RAG/shared-policy stack. TASK-41 is a diagnostic attempt: 50
attempted, 47 scored, 45 matched, two false escalations, three operational
failures and zero false simulated sends; failed batches do not overwrite the
accepted historical tracker.
**Status:** active; documentation only. Workflow/retrieval failures, current
200-case validation, sequential comparison, scale and live-release gates remain open.

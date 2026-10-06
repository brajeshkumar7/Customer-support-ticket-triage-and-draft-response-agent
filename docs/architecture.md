# Implemented architecture

The local graph, interactive Zoho runner and controlled worker are separate
paths. Real customer auto-send is disabled. The worker is implemented but
undeployed; its `live` mode refuses startup.

## Local graph

```mermaid
flowchart TD
    A[Ticket text and internal run ID] --> B[Recall Chroma historical summaries]
    B --> C[Jev typed category and urgency; derive P1/P2/P3]
    C --> D[gather_facts: hybrid PDF retrieval and bounded evidence review]
    D --> E{Supported informational intent?}
    E -->|Yes| F[Skip extraction and fixture tools]
    E -->|No| G[Extract explicit order ID and reason]
    G --> H[Concurrent order lookup, shared-policy check, FAQ search]
    H --> I[Deterministic safety and policy-evidence consistency]
    F --> I
    I --> J[Exact approved FAQ text or cited human-review draft]
    J --> K[Local exact-template check or Jev three-check review]
    K -->|Eligible FAIL; retries left| R[prepare_retry: feedback; max 3 retries]
    R --> J
    K -->|Safety allowed and PASS| S[Simulation-only sender]
    S -->|Confirmed simulation| M[Remember compact summary]
    M --> END1[END: simulated sent]
    K -->|Blocked, uncertain, failed or exhausted| X[Complete human escalation]
    S -->|No sender or delivery failure| X
    C -->|Unclear or failed classification| X
    D -->|Operational failure| X
    J -->|Operational failure| X
    X --> END2[END: escalated]
```

The graph topology is `recall → classify → gather_facts → safety_review →
respond → supervisor`, followed by bounded retry, simulated delivery and
remember, or escalation. Guarded operational errors escalate; Chroma recall/
storage errors are nonfatal and visible in state. A blocked safety gate cannot
be overridden by supervisor PASS. Escalation includes ticket, tool results,
failed drafts with feedback and a human-readable reason; it does not assign a
Zoho human by itself.

### Models, tools and evidence

With RAG enabled every ticket uses Jev category/urgency Choices through
OpenRouter Decisions. Generative chat calls perform evidence review, explicit
ticket-detail extraction when needed, and cited human drafts. Generated drafts
receive one Jev Decisions request with three checklist questions. Each must
select `pass` with probability at least 0.90; uncertainty/malformed responses
are non-approval. This provisional threshold is not calibrated. Fixed reasons
provide feedback, not sentence-level unsupported-claim identification.
Exact approved FAQ templates are checked locally without a supervisor API call.
The checklist completion score is separate from Jev probabilities.

Only fixed application-owned tools run; no model-generated code or shell
commands execute. Docker is an unused placeholder, not a security boundary.
The order fixture is fictional. The validated
[shared business policy](../data/policies/support_v1.json) supplies eligibility
rules and generated PDF text. Policy results require matching active retrieved
ID/version/hash/rule metadata; obsolete policy references are filtered.
Business-policy provenance is separate from send policy `informational_only_v4`.

[The 13-PDF corpus](../knowledgebase/README.md) uses dense MiniLM Chroma and
sparse BM25 SQLite, fused by RRF. The search agent may use at most three
allowlisted searches per gather step. Citation validity is not proof of
entailment, requester identity or authority. Informational simulation approval
requires scoped, hash-pinned evidence and exact versioned reply text.
Unreviewed/reference-only PDFs cannot authorize sending.

Short-term state is per run. Ordinary sample and Zoho runs use persistent
Chroma; single synthetic runs use fresh ephemeral memory. Complete 50/200-case
batches share fresh ephemeral historical memory; persistent history is untouched.
Only confirmed successful simulations are remembered. Recall never verifies
current business facts and is excluded from approval/supervisor factual evidence.

Node/tool/model events go to JSONL. Local logs may contain bodies/drafts;
worker logs omit them. LangGraph async update streaming emits completed node
updates, not token streams. See [commands](../README.md).

## Interactive Zoho runner

`run_zoho` fetches an existing ticket's subject/description, runs the graph with
delivery disabled, and prints the draft and findings. Usable ticket text can
be analyzed across channels. `--send-reviewed` is a separate, controlled human
send: review exact text and confirm requester/ticket; PASS proposes the draft,
otherwise a fixed acknowledgement is proposed. Ticket changes block sending;
an uncertain send is never automatically repeated. This path is not polling,
latest-thread ingestion or unattended customer support.

## Separate controlled worker

```mermaid
flowchart TD
    A{Startup mode} -->|off| O[Wait; no polling]
    A -->|live| L[Reject startup]
    A -->|shadow or test| B[Poll Zoho changed Email tickets and latest inbound thread]
    B --> C[PostgreSQL unique organization-ticket-thread job]
    C --> D[Informational decision with approved local knowledge]
    D -->|shadow| SH[Record only; no Zoho write]
    D -->|test| E[Exact allowlist, expiry, owner-approved hash and kill switch]
    E --> F[Refetch ticket and check requester, channel, status and latest thread]
    F -->|Blocked| H[Human job; private note for allowed test ticket]
    F -->|Eligible| G[Persist sending state and digest; one public template reply]
    G -->|Confirmed thread ID| S[Persist sent record]
    G -->|Uncertain or restart during send| U[Unknown; reconcile without resending]
    U -->|Unresolved| H
```

The worker does not call the graph, draft model prose or use Chroma approval
evidence. Repository knowledge is still `review_required`; owner approval is
an additional requirement. Paid Render/PostgreSQL are selected but not deployed.
Polling/restart/reconciliation need controlled integration validation. Real
release additionally requires authoritative sources, identity verification,
independently reviewed tickets and a separate live decision. See
[deployment prerequisites](controlled_render.md).

# Local knowledge and evaluation audit — 2026-10-04

## What the agent can actually use

| Source | Current content | Role in the graph | Limit |
| --- | --- | --- | --- |
| `data/mock_orders.json` | Six invented orders | Order lookup and policy input | No live order, shipment, requester, or billing verification |
| `src/tools/policy_checker.py` | Fixed 30-day return and 7-day damage rules | Computes fixture eligibility | No approved merchant policy, warranty, exception, or jurisdiction logic |
| `src/tools/faq_search.py` | Six hardcoded answers, retrieved by keyword overlap | General support context | A keyword hit does not establish relevance or factual authority |
| Local Chroma | Summaries produced by past runs | Historical recall in ordinary graph runs | Prior agent output is not a verified business source; complete 50/200-case batches use a fresh shared ephemeral collection, with sequential 50-case ticket order |
| `data/approved_knowledge/v1.json` | Versioned FAQ templates with local simulation provenance; top-level `review_required` | The graph uses exact templates for simulated informational replies; the controlled worker requires separate owner approval | Example merchant content, not authorized for real customer delivery |
| `data/knowledge_sources.json` | Cited public research summaries | Human review only | Not loaded by the agent; does not approve a policy or verify any ticket |

## Public-source review

- The [FTC online shopping guidance](https://consumer.ftc.gov/articles/online-shopping) directs shoppers to check the *seller's* return, refund, and delivery terms. It cannot establish this project's 30-day or 7-day rules, which remain synthetic assumptions.
- The [PCI Security Standards Council guidance](https://www.pcisecuritystandards.org/faqs/1157/) addresses card data arriving through an unintended channel. It is useful for a future safety review, but it cannot confirm a customer's charge or refund.
- The [USPS tracking guidance](https://faq.usps.com/articles/Knowledge/Where-is-my-package) describes USPS states. The mock orders have no verified USPS tracking feed, so these states cannot be presented as their live status.
- [OWASP's excessive-agency guidance](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) supports limiting the agent's tools and independently enforcing permission before downstream actions. It is not merchant reply content.
- [NIST's AI RMF Measure guidance](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) calls for documented test sets, deployment-relevant evaluation, and independent review to reduce internal bias. This is why author-labeled synthetic scores remain separate from a live release decision.

These sources are recorded locally with scope and provenance in `data/knowledge_sources.json`. None has been copied into sendable answers, policy logic, or Chroma. Public pages may be useful reference material, but they cannot replace a merchant's approved policy, a live commerce system, or verified customer identity.

## Offline 50-ticket coverage check

This check loaded `data/test_tickets/tickets.jsonl`, joined each case to `manifest.csv`, and ran the existing FAQ keyword matcher. It made no model or Zoho calls.

| Category | Tickets | With at least one FAQ keyword hit | Without a hit |
| --- | ---: | ---: | ---: |
| Order status | 10 | 6 | 4 |
| Returns | 10 | 10 | 0 |
| Damaged item | 10 | 8 | 2 |
| Billing dispute | 10 | 8 | 2 |
| General question | 10 | 9 | 1 |
| **Total** | **50** | **41** | **9** |

No-hit case IDs: `order_03`, `order_05`, `order_06`, `order_08`, `damage_04`, `damage_09`, `billing_03`, `billing_04`, `general_05`.

This is *retrieval coverage only*. The matcher can return a loosely related FAQ; it does not measure answer correctness, whether the graph escalates appropriately, latency, or cost. Ten billing cases are labeled for escalation because there is no billing ledger; giving them a generic FAQ match does not make them answerable. Some no-hit cases likewise require order verification or human judgment, so adding keywords to force 50 hits would not improve safety.

## Pre-fix 50-ticket result

The complete simulated-delivery run is saved in
`data/eval_reports/task27_20261004T133253Z_f6336e28.json` and published in
`PROGRESS.md`. It scored 50/50 runs, with 46/50 expected dispositions matched,
24/28 expected escalations correctly escalated, four false simulated sends,
and 53212.16329996241 ms p95 full-run latency. The fake sender made no
public Zoho replies. The earlier 25-ticket reports remain historical and
cannot be projected onto the expanded set.

For the seven author-labeled, expected-to-auto-resolve general-question cases,
the nearest-rank p95 was 55911.06130002299 ms. For the 15 expected-to-
auto-resolve order, return, and damage cases, it was 53212.16329996241 ms.
Those subsets are small and do not establish deployment latency, but the
general-question result exceeds the project's 30-second FAQ reply target.

All four errors were tickets labeled for escalation that passed supervisor
review and the deterministic safety gate:

| Case | Required human handling | What the report shows |
| --- | --- | --- |
| `order_08` | Customer disputes an order marked delivered; investigate actual delivery | A clarification draft was treated as sendable without resolving the dispute |
| `damage_09` | Possible electrical hazard and explicit request for safety review | The model gave precautionary guidance, but the gate permitted a simulated send |
| `general_09` | Requested overnight service and price are absent from the merchant's policy data | An inability-to-verify draft was treated as a complete customer reply |
| `general_10` | Customer requests an account/address change that the agent cannot perform | A request for the order number was treated as a complete customer reply |

These were decision and task-completion errors; copying more generic web pages
into a vector store would not verify a delivery dispute, open a safety review,
approve an overnight rate, or change an address.

## Post-fix 50-ticket result

The complete post-fix fake-sender report is
`data/eval_reports/task27_20261004T145739Z_b321d04c.json`. It matched 50/50
expected dispositions, with 0/28 false simulated sends, 0/22 false
escalations, 45100.53940000944 ms overall p95, and 0.13817527
provider-reported token cost. All four previously missed cases escalated. The
expanded offline gate set matched 31/31 author-labeled decisions. No public
Zoho reply was sent.

The seven answerable general-question cases had 45825.03159996122 ms p95,
still above the 30-second FAQ target. The 15 answerable order, return, and
damage cases had 58759.3077000347 ms p95. These small synthetic subsets do
not establish deployment latency. Real customer release still needs
authoritative provider data and independently reviewed cases, as recorded in
`TASKS.md`.

## TASK-29 local informational policy

The graph and controlled worker now call the same decision function for
informational approval. `data/approved_knowledge/v1.json` records an entry ID,
scope, local fictional-merchant provenance, and `simulation` review status for
each reply. The top-level status remains `review_required`, so this content
does not satisfy the controlled worker's owner-approved sending check. The
graph's fake sender can exercise these replies locally; it does not send to a
customer. Mock order records and Chroma summaries cannot approve a public
reply. A future provider contract can reject requester mismatches, stale
snapshots, and contradictory shipment facts, but no real provider supplies
those records yet.

`manifest.csv` retains the older fixture-backed labels. The new
`manifest_informational.csv` labels seven general FAQ tickets auto-resolvable
and 43 tickets for human review. `holdout_v1.jsonl` is a frozen, author-labeled,
templated 200-case synthetic set, not an independently reviewed release set.
Public guidance in `data/knowledge_sources.json` remains a research reference,
not merchant policy or customer-specific evidence.

## TASK-29 measured 50-case regression

The saved fake-sender report is
`data/eval_reports/task27_20261004T184541Z_e77207d7.json`; a versionable
measurement without ticket or draft text is
`docs/measurements/task29_50.json` (the local report filename
retains the earlier report prefix; its metadata identifies TASK-29 and the
informational-only manifest). This run preceded the v3 completeness and refund-prerequisite guards
and is historical, superseded by the v3 run below. All 50 author-labeled cases matched the revised
disposition: seven exact FAQ templates were simulated as sent, and 43 cases
escalated. There were zero false simulated sends and zero false escalations
against these labels. No Zoho reply was posted.

The nearest-rank p95 for the seven simulated FAQ replies was
2005.5652000010014 ms, below the local 30-second FAQ target. Across all 50
cases, p95 was 39862.9492999753 ms; human-review cases still made model
calls. The run logged 172 LLM calls and 0.111505525 in provider-reported
token cost. Seven approved FAQ cases made no LLM call and therefore had
known zero token cost, not missing cost. These are local full-run timings and
author-drafted labels; neither establishes real customer accuracy or
arrival-to-reply latency.

## TASK-29 v3 and 200-case synthetic regression (2026-10-05)

The historical v3 50-case regression is saved at
`data/eval_reports/task29_20261005T062249Z_c30b0b20.json`; its public-safe
summary is `docs/measurements/task29_50_v3.json`. It matched 50/50 labels,
with zero false simulated sends, zero false escalations, 21 review drafts
flagged for unsupported claims, p95 42986.12800000001 ms, and reported token
cost 0.110459985.

The 200-case, hash-pinned, author-labeled holdout report is
`data/eval_reports/holdout_v1_20261005T064737Z_9b17b234.json`; the shareable
summary is `docs/measurements/task29_holdout_v1.json`. It matched 189/200
(0.945), below the 0.95 local target. There were zero false simulated sends,
zero unsupported public claims, and 21/21 simulated replies had required
evidence; 11 informational cases were falsely escalated, all in
`general_question`. Total reported token cost was 0.45285409 across 716
model calls; full-run p95 was 59722.046200000026 ms and approved FAQ p95 was
714.4188000002032 ms. These test phrases were visible to the developer and
templated, so this is a reproducible local regression, not independent
validation. Real customer sending remains blocked.
By-category model calls and reported costs were: order status 160 / 0.0969393,
returns 160 / 0.101812, damaged item 160 / 0.1056493, billing dispute 160 /
0.10040729, and general questions 76 / 0.0480462. All 716 completed LLM
responses were attributed by the log's response model to
`openai/gpt-6-luna-pro`; no fallback model calls were recorded.

## Latest completed 50-case regression and recall scope

The later completed report
`data/eval_reports/task29_20261005T183529Z_2979caa5.json` records
`shared_ephemeral_chroma_sequential`: one fresh collection for all 50 tickets,
processed in order. It matched 50/50 author-drafted labels with seven
simulated FAQ replies, 43 escalations, zero false simulated sends, p95
44778.41449999687 ms, and 0.115013845 provider-reported token cost. This
run predates the final TASK-32 triage edit. The older 200-case report above
did not prove the same effective recall scope; a comparable rerun is pending.

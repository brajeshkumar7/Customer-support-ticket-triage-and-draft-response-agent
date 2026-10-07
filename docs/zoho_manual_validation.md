# Manual Zoho integration validation

Recorded on 2026-10-07 from terminal output and inbox confirmations the owner
shared in the project conversation. This is a retrospective record; individual
run dates and complete model/configuration snapshots were not supplied for all
observations. These runs span older and current implementations.

## Observed outcomes

| Manual check | Shared evidence and outcome | What it establishes |
| --- | --- | --- |
| OAuth refresh | The command printed `Zoho OAuth refresh succeeded.` | The configured credentials could obtain an access token at that time. |
| Ticket lookup | Shared API output contained ticket numbers and their distinct API `id` values. | Ticket retrieval worked; displayed ticket numbers are not interchangeable with API IDs. |
| Historical agent delivery | Earlier graph runs showed supervisor `PASS`, terminal status `sent`, delivery status `sent`, and `response_sent: true`. | The older agent-to-Zoho path reported successful API delivery. These outputs alone do not prove inbox receipt or answer correctness. |
| Historical channel restriction | One ticket was refused because it was not an Email ticket, with no agent run or reply. | The older command enforced its channel restriction. Current draft runs accept other channels; email eligibility remains checked separately. |
| Deterministic safety block | Later agent runs categorized and prioritized the ticket, produced a human-review draft, and escalated with `customer_facts_unverified`. | Fixture facts did not authorize unattended customer-specific delivery. |
| Recipient confirmation refusal | The operator entered a different address from the displayed requester; the command reported that no email was sent. | The manual recipient confirmation prevented that send attempt. |
| Reviewed acknowledgement | The command displayed a fixed acknowledgement after draft review failed. The owner subsequently reported receiving the email. | The controlled, manually confirmed acknowledgement path worked, including user-reported inbox receipt. This was not delivery of the failed agent draft. |
| Later Jev-reviewed run | Shared follow-up discussions reported non-approval and a fixed acknowledgement; after initially reporting no email, the owner confirmed receipt. | A further user-reported acknowledgement receipt; this does not validate Jev calibration or customer-specific draft correctness. |

Earlier attempts also exposed HTTP 404 with a displayed ticket number, HTTP 403
during lookup, a missing logger argument, and stdin/confirmation errors. Later
successful observations do not erase those failures. Existing failure and
session records retain their investigations and fixes.

## Interpretation and limits

These are **manual integration tests on owner-controlled tickets and contacts**.
They are not a standardized labeled evaluation, an exhaustive run inventory,
or validation of the current configuration on every historical path. No success
rate, accuracy, latency, cost, or total unique send count is calculated from
these anecdotes. Duplicate excerpts and repeated runs must not be counted as
independent benchmark cases.

The latest [50-ticket benchmark](measurements/task43_regression.json) used a fake
sender and made no Zoho requests. Its accuracy and cost figures exclude all
of these manual observations. The separate controlled worker's polling,
deduplication, restart recovery and human routing remain unvalidated with live
Zoho; it has not been deployed.

Current behavior and commands are documented in [README](../README.md#4-controlled-zoho-runs).
The graph remains draft-only for Zoho. A manually confirmed email can be sent
through `run_zoho --send-reviewed`; failed drafts use the fixed acknowledgement.
The delivery-only smoke command does not exercise the agent. This record does
not authorize unattended real-customer delivery or claim production accuracy.

For future manual runs, retain the local run ID, configuration, returned Zoho
thread ID, chosen message type and inbox confirmation privately. Do not publish
credentials, requester addresses or ticket bodies with showcase evidence.

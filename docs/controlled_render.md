# Controlled Render worker (release status: not deployed)

This worker is a **test-only demonstration**, not customer automation. It
polls Zoho every 60 seconds and recognizes the newest inbound Email thread.
It writes one PostgreSQL job per organization, ticket, and inbound thread.
Shadow mode stores decisions without changing Zoho. Test mode can send an
informational reply only when all of these hold:

1. The exact ticket API ID and requester email have a live, unexpired database
   allowlist entry. This must be a ticket and contact the operator controls.
2. The database test-send kill switch is enabled.
3. `data/approved_knowledge/v1.json` has been reviewed by a support-policy
   owner, changed from `review_required` to `approved`, and its exact SHA-256
   is configured as `APPROVED_KNOWLEDGE_SHA256`.
4. The current Zoho ticket, requester, inbound sender email, channel, status,
   and newest thread still match. No newer human or agent reply exists.
   Missing sender data, truncated content, or quoted email history blocks
   automatic sending.
5. The request matches one of four informational template types. Order,
   shipment, billing, account, refund-action, safety, manager, ambiguous,
   and discretionary requests are sent to a human. No commerce action runs.

`DEPLOYMENT_MODE` defaults to `off`. `live` intentionally fails startup until
authoritative commerce/billing providers and a separate release decision are
implemented. `ZOHO_DESK_SEND_ENABLED` does not override these gates.

## Prepare and deploy

`render.yaml` describes **paid** Render resources: one worker and one private
PostgreSQL database. Review the plan and cost in Render before syncing it.
Fill its Zoho OAuth secrets in the Render secret settings. The database URL is
injected by the Blueprint; never commit credentials. Begin with
`DEPLOYMENT_MODE=shadow`. Monitor worker logs and the PostgreSQL job ledger.
Rotate any Zoho client secret or refresh token previously pasted into chat or
shared files before using this deployment.
Zoho API credentials need ticket read/update permissions and a private-note
permission where applicable. Confirm regional domains and the organization ID.
The worker never uses the Docker sandbox or local Chroma for outbound text.

To approve reference text, the support-policy owner reviews each sentence in
`data/approved_knowledge/v1.json`, changes `status` to `approved`, and records
their approval in the deployment change record. Compute the file hash with:

```powershell
Get-FileHash data/approved_knowledge/v1.json -Algorithm SHA256
```

Set `APPROVED_KNOWLEDGE_SHA256` to that hash. Any later file change invalidates
the approval until a new review and hash update.

For a controlled test, change `DEPLOYMENT_MODE=test`, then add the precise
Zoho API ticket ID, controlled requester email, and UTC expiration in the
worker shell:

```powershell
$testExpiry = (Get-Date).ToUniversalTime().AddDays(1).ToString("yyyy-MM-ddTHH:mm:ssZ")
python -m src.agent.worker_admin allow-test-ticket --ticket-id 123456789 --email controlled@example.com --expires $testExpiry
python -m src.agent.worker_admin enable-test-sending
```

Stop test sends immediately with:

```powershell
python -m src.agent.worker_admin disable-test-sending
```

The switch is stored in PostgreSQL, so it takes effect without a new deploy.
The worker also checks it immediately before sending. Test credentials and
allowlist entries must use only controlled contacts. Keep a single worker
instance; horizontal scaling needs an additional cross-worker rate budget and
claiming design. The current Zoho polling cursor has a two-minute overlap and
unique job keys but cannot guarantee no missed event under arbitrary API
reordering or outages; monitor backlog and reconcile against Zoho.

## Failure and recovery

Before sending, the job becomes `sending`. A worker restart converts unfinished
jobs to `unknown`. A timeout or missing Zoho reply thread ID is also `unknown`.
The worker searches Zoho for a matching outgoing thread and can mark it sent;
it **never automatically retries** an unknown send. A human must inspect
unresolved unknown jobs. Confirmed blocked cases are recorded as `human` and,
for allowlisted test tickets, receive a private note. If note posting fails,
the PostgreSQL job remains the human work queue.

The database retains only identifiers, email for the controlled allowlist,
state, reason code, and a reply digest. The worker purges expired allowlist
entries and completed jobs older than 30 days. Human and unknown jobs remain
until a reviewer verifies Zoho and runs
`python -m src.agent.worker_admin mark-reviewed --ticket-id ID --thread-id ID`.
Use Render's paid database backups and
restrict database access. Deployment JSONL logging omits ticket text and
drafts. Audit access to Zoho and the database separately.

## Release gate still outstanding

The saved 25-case simulated benchmark predates this controlled worker. It is
not proof of safe customer sending. The release evaluator requires at least
200 cases with explicit human reviewer attribution and coverage across all
five categories. It measures the offline deterministic decision only; wrong
recipient attempts, duplicates, source staleness, and arrival-to-reply time
require controlled integration tests and shadow observations. Review at least
100 representative real shadow decisions, contract-test actual authorized
order/shipment/billing/policy sources, and record a separate live decision.
Until then, `live` cannot start.

## API and hosting references

- [Zoho Desk API: ticket listing, pagination, and ticket/thread endpoints](https://desk.zoho.com/DeskAPIDocument)
- [Zoho Desk webhook availability by edition](https://help.zoho.com/portal/en/kb/desk/automation/webhooks/articles/setting-up-webhooks-in-zoho-desk)
- [Render background workers](https://render.com/docs/background-workers)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render PostgreSQL backups](https://render.com/docs/postgresql-backups)

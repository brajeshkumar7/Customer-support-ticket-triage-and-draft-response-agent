# Agent run-history dashboard

Local read-only Next.js App Router + strict TypeScript, requiring Node 20.9+
and npm. Logs are read on the server; rendered log values are shown in the
browser. No external model/Zoho API, authentication or write operation is added.

From the repository root:

```powershell
cd dashboard
npm install
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Open <http://localhost:3000>. `LOGS_DIR` defaults to `../data/logs`, relative to
`dashboard/`, or can be absolute. On Linux/macOS use
`[ -f .env.local ] || cp .env.example .env.local`. Reload manually for new events.

```powershell
npm run lint
npm run build
npm run start
```

Stop dev before starting on the same port. `start` needs a completed build.
The server reads only direct regular `.jsonl` files; invalid names containing
separators or `..` are rejected. Malformed/invalid lines are skipped with a
visible count. Choose a file, filter by run ID and expand logged input/output
with native details elements. Missing values show `—`; status is derived per
event only when logged evidence exists. This is not an independent run verdict.
Local logs may contain private ticket text; do not expose this debugger publicly.
See [all project commands](../README.md).

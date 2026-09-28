# Agent run-history dashboard

This local, read-only Next.js dashboard displays JSONL events written by the
Python agent. It reads logs on the server and does not send log data to a
browser-side API.

## Run locally

```powershell
npm install
npm run dev
```

Open <http://localhost:3000>. By default, the dashboard reads `../data/logs`
relative to this directory. To use another directory, copy `.env.example` to
`.env.local` and set `LOGS_DIR` to an absolute path or a path relative to
`dashboard/`. Refresh the page to load new events.

The dashboard lists direct `.jsonl` files, skips malformed lines with a visible
count, and supports selecting a file and filtering by run ID. It is a local
debugging tool and has no authentication or write operations.

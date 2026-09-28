import { notFound } from "next/navigation";
import {
  formatLogValue,
  getEventName,
  getEventStatus,
  listLogFiles,
  readLogFile,
  type JsonValue,
  type LogEvent,
} from "@/lib/logs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type PageProps = {
  searchParams: Promise<{
    file?: string | string[];
    runId?: string | string[];
  }>;
};

function getSingleParameter(value: string | string[] | undefined):
  | { value: string | undefined; invalid: false }
  | { value: undefined; invalid: true } {
  if (Array.isArray(value)) {
    return { value: undefined, invalid: true };
  }
  return { value, invalid: false };
}

function displayValue(value: JsonValue | undefined): string {
  return formatLogValue(value);
}

function preview(value: string, maxLength = 150): string {
  const compact = value.replace(/\s+/g, " ");
  return compact.length > maxLength
    ? `${compact.slice(0, maxLength)}...`
    : compact || "—";
}

function EventDetails({
  label,
  value,
}: {
  label: string;
  value: JsonValue | undefined;
}) {
  if (value === undefined) {
    return <span className="muted">—</span>;
  }

  const formatted = displayValue(value);
  return (
    <details className="payload-details">
      <summary title={`Expand ${label}`}>{preview(formatted)}</summary>
      <pre>{formatted}</pre>
    </details>
  );
}

function getStatusLabel(event: LogEvent): string | undefined {
  return getEventStatus(event);
}

export default async function Home({ searchParams }: PageProps) {
  const params = await searchParams;
  const requestedFile = getSingleParameter(params.file);
  const requestedRunId = getSingleParameter(params.runId);
  if (requestedFile.invalid || requestedRunId.invalid) {
    notFound();
  }

  const files = await listLogFiles();
  if (
    requestedFile.value !== undefined &&
    !files.some((file) => file.name === requestedFile.value)
  ) {
    notFound();
  }

  const selectedFile = requestedFile.value ?? files[0]?.name;
  const runIdFilter = requestedRunId.value ?? "";
  const parsedLog = selectedFile
    ? await readLogFile(selectedFile)
    : { events: [], skippedLines: 0 };
  const filteredEvents = runIdFilter.trim()
    ? parsedLog.events.filter((event) =>
        event.run_id?.toLocaleLowerCase().includes(runIdFilter.trim().toLocaleLowerCase()),
      )
    : parsedLog.events;

  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Local observability</p>
          <h1>Agent run history</h1>
          <p className="subtitle">
            Inspect recorded graph events, tool calls, and model requests.
          </p>
        </div>
        <div className="header-note">Read-only · server-side log access</div>
      </header>

      <section className="panel controls-panel" aria-label="Log filters">
        <form action="/" method="get" className="controls-form">
          <label className="control-group" htmlFor="log-file">
            <span>Log file</span>
            <select id="log-file" name="file" defaultValue={selectedFile ?? ""}>
              {files.length === 0 ? <option value="">No log files found</option> : null}
              {files.map((file) => (
                <option key={file.name} value={file.name}>
                  {file.name}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group run-filter" htmlFor="run-id">
            <span>Run ID contains</span>
            <input
              id="run-id"
              name="runId"
              type="search"
              defaultValue={runIdFilter}
              placeholder="Filter by run ID"
            />
          </label>
          <button type="submit" disabled={files.length === 0}>
            Apply filters
          </button>
          {runIdFilter ? (
            <a
              className="clear-filter"
              href={selectedFile ? `/?file=${encodeURIComponent(selectedFile)}` : "/"}
            >
              Clear run filter
            </a>
          ) : null}
        </form>
        {selectedFile ? (
          <p className="file-summary">
            Showing {filteredEvents.length} of {parsedLog.events.length} events from{" "}
            <strong>{selectedFile}</strong>. Skipped {parsedLog.skippedLines} malformed or
            invalid {parsedLog.skippedLines === 1 ? "line" : "lines"}.
          </p>
        ) : (
          <p className="file-summary">
            No .jsonl files were found in the configured logs directory.
          </p>
        )}
      </section>

      <section className="panel table-panel" aria-label="Run events">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Timestamp</th>
                <th scope="col">Run / ticket ID</th>
                <th scope="col">Node / tool</th>
                <th scope="col" className="numeric">Latency (ms)</th>
                <th scope="col" className="numeric">Token cost</th>
                <th scope="col">Status</th>
                <th scope="col">Input</th>
                <th scope="col">Output</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.length === 0 ? (
                <tr>
                  <td className="empty-row" colSpan={8}>
                    {selectedFile
                      ? "No events match this run ID filter."
                      : "Choose a log file after adding JSONL events to data/logs/."}
                  </td>
                </tr>
              ) : (
                filteredEvents.map((event, index) => {
                  const status = getStatusLabel(event);
                  const eventName = getEventName(event);
                  return (
                    <tr key={`${event.timestamp}-${event.event_type}-${index}`}>
                      <td className="timestamp-cell">
                        <time dateTime={event.timestamp}>{event.timestamp}</time>
                      </td>
                      <td>{event.run_id ?? <span className="muted">—</span>}</td>
                      <td>
                        <span className="event-name">{eventName ?? "—"}</span>
                        <span className="event-type">{event.event_type}</span>
                      </td>
                      <td className="numeric">{event.latency_ms.toFixed(3)}</td>
                      <td className="numeric">
                        {event.token_cost == null ? "—" : event.token_cost.toString()}
                      </td>
                      <td>
                        {status ? (
                          <span className={`status status-${status}`}>{status}</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="payload-cell">
                        <EventDetails label="input" value={event.inputs} />
                      </td>
                      <td className="payload-cell">
                        <EventDetails label="output" value={event.output} />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
      <footer className="page-footer">
        Data is read from local JSONL files. Refresh the page to load new events.
      </footer>
    </main>
  );
}

import { createReadStream } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import path from "node:path";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type LogEventType =
  | "node_transition"
  | "tool_call"
  | "llm_call"
  | "rate_limit";

export type LogEvent = {
  timestamp: string;
  event_type: LogEventType;
  inputs: JsonValue;
  output: JsonValue;
  latency_ms: number;
  run_id?: string;
  name?: string;
  node_name?: string;
  tool_name?: string;
  call_name?: string;
  token_cost?: number | null;
  error?: JsonValue;
};

export type LogFile = {
  name: string;
  modifiedAt: number;
};

export type ParsedLog = {
  events: LogEvent[];
  skippedLines: number;
};

const EVENT_TYPES = new Set<string>([
  "node_transition",
  "tool_call",
  "llm_call",
  "rate_limit",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  return (
    isRecord(value) && Object.values(value).every(isJsonValue)
  );
}

function isOptionalStringField(
  record: Record<string, unknown>,
  field: string,
): boolean {
  return record[field] === undefined || typeof record[field] === "string";
}

function isLogEvent(value: unknown): value is LogEvent {
  if (!isRecord(value)) {
    return false;
  }

  if (
    typeof value.timestamp !== "string" ||
    typeof value.event_type !== "string" ||
    !EVENT_TYPES.has(value.event_type) ||
    !isJsonValue(value.inputs) ||
    !isJsonValue(value.output) ||
    typeof value.latency_ms !== "number" ||
    !Number.isFinite(value.latency_ms)
  ) {
    return false;
  }

  if (
    !isOptionalStringField(value, "run_id") ||
    !isOptionalStringField(value, "name") ||
    !isOptionalStringField(value, "node_name") ||
    !isOptionalStringField(value, "tool_name") ||
    !isOptionalStringField(value, "call_name")
  ) {
    return false;
  }

  if (
    value.token_cost !== undefined &&
    value.token_cost !== null &&
    (typeof value.token_cost !== "number" || !Number.isFinite(value.token_cost))
  ) {
    return false;
  }

  return value.error === undefined || isJsonValue(value.error);
}

export function isSafeLogFilename(filename: string): boolean {
  return (
    filename.endsWith(".jsonl") &&
    !filename.includes("..") &&
    !filename.includes("/") &&
    !filename.includes("\\")
  );
}

export function getLogsDirectory(): string {
  const configuredDirectory = process.env.LOGS_DIR?.trim() || "../data/logs";
  return path.resolve(process.cwd(), configuredDirectory);
}

export async function listLogFiles(): Promise<LogFile[]> {
  const directory = getLogsDirectory();
  let entries;

  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (isRecord(error) && error.code === "ENOENT") {
      return [];
    }
    throw error;
  }

  const files = await Promise.all(
    entries
      .filter((entry) => entry.isFile() && isSafeLogFilename(entry.name))
      .map(async (entry): Promise<LogFile> => {
        const fileStats = await stat(path.join(directory, entry.name));
        return { name: entry.name, modifiedAt: fileStats.mtimeMs };
      }),
  );

  return files.sort((left, right) => right.modifiedAt - left.modifiedAt);
}

export async function readLogFile(filename: string): Promise<ParsedLog> {
  if (!isSafeLogFilename(filename)) {
    throw new Error("Invalid log filename.");
  }

  const directory = getLogsDirectory();
  const files = await listLogFiles();
  if (!files.some((file) => file.name === filename)) {
    throw new Error("Log file is not available.");
  }

  const events: LogEvent[] = [];
  let skippedLines = 0;
  const stream = createReadStream(path.join(directory, filename), {
    encoding: "utf-8",
  });
  const lines = createInterface({ input: stream, crlfDelay: Infinity });

  for await (const line of lines) {
    if (!line.trim()) {
      continue;
    }

    try {
      const parsed: unknown = JSON.parse(line);
      if (isLogEvent(parsed)) {
        events.push(parsed);
      } else {
        skippedLines += 1;
      }
    } catch {
      skippedLines += 1;
    }
  }

  events.sort((left, right) => right.timestamp.localeCompare(left.timestamp));
  return { events, skippedLines };
}

export function getEventName(event: LogEvent): string | undefined {
  return event.node_name ?? event.tool_name ?? event.call_name ?? event.name;
}

export function getEventStatus(event: LogEvent):
  | "pass"
  | "fail"
  | "escalated"
  | undefined {
  if (event.error !== undefined && event.error !== null) {
    return "fail";
  }

  const output = isRecord(event.output) ? event.output : undefined;
  if (!output) {
    return undefined;
  }

  if (output.supervisor_status === "PASS") {
    return "pass";
  }
  if (output.supervisor_status === "FAIL") {
    return "fail";
  }
  if (output.escalated === true || output.terminal_status === "escalated") {
    return "escalated";
  }
  if (
    output.response_sent === true ||
    output.terminal_status === "sent" ||
    output.zoho_delivery_status === "sent"
  ) {
    return "pass";
  }
  if (
    output.zoho_delivery_status === "failed" ||
    output.zoho_delivery_status === "unknown" ||
    output.zoho_delivery_status === "missing_ticket_id" ||
    output.zoho_delivery_status === "not_configured" ||
    output.zoho_delivery_status === "confidence_blocked"
  ) {
    return "fail";
  }
  if (
    (event.event_type === "tool_call" || event.event_type === "llm_call") &&
    event.output !== null
  ) {
    return "pass";
  }

  return undefined;
}

export function formatLogValue(value: JsonValue | undefined): string {
  if (value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

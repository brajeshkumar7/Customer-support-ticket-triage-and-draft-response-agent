"""
Structured logging for every tool call: input, output, latency, token cost.
Implements PRD.md Section 6 (Observability Requirements).
Writes to data/logs/ as JSON lines for the dashboard to read.
"""

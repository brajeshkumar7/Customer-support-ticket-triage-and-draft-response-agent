"""
Short-term (per-run) working state. Implements PRD.md Section 4: Memory.
Start with a plain in-memory dict per AGENTS.md tech stack notes (free-tier
first pass); swap to Redis only if a real need for cross-process state shows
up - log that decision in DECISIONS.md before switching.
"""

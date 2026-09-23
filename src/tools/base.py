"""
Shared tool interface/base class. All tools should:
- log call, input, output, latency, token cost (PRD.md Section 6, Observability)
- raise a typed, catchable error on failure (never let a tool crash the graph)
- treat their own output as untrusted before it re-enters agent context
  (PRD.md Section 4, Adversarial input handling)
"""

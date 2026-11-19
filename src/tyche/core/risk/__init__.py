"""The risk layer (pipeline stage 5): an independent gate nothing can bypass.

Available now: ``PassThroughGate``, which approves every proposed portfolio unchanged,
so the event flow is already the final one (Phase 1).

Planned (Phase 2): named risk profiles, hard guardrails, per-strategy overrides that
may only be stricter, the rules inside the gate, and halts (daily loss limit, drawdown
kill switch).
"""

from tyche.core.risk.gate import PASS_THROUGH, PassThroughGate

__all__ = ["PASS_THROUGH", "PassThroughGate"]

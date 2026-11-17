"""The risk layer (pipeline stage 5): an independent gate nothing can bypass.

Planned (Phase 2): named risk profiles, hard guardrails, per-strategy overrides that
may only be stricter, the gate that turns a proposed ``TargetPortfolioEvent`` into an
``ApprovedPortfolioEvent``, and halts (daily loss limit, drawdown kill switch).
"""

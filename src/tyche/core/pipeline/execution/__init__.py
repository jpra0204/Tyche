"""Stage 6, execution: approved targets become orders.

Planned (Phase 1 for the simulator, Phase 2 for IBKR): diffs approved targets against
current positions, creates idempotent orders and tracks each through its lifecycle.
Accepts only ``ApprovedPortfolioEvent`` (ADR-0006).
"""

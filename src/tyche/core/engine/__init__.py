"""The run loop that wires pipeline stages to the event bus.

Planned (Phase 1): one engine for backtest, paper and live. It receives a clock, a
data feed and a broker and does not know which mode it is in (ADR-0005).
"""

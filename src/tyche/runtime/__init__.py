"""The composition root: the one place that knows about both core and adapters.

Planned (Phase 1 onward): builds an engine for a given mode by choosing the clock,
feed and broker; later the scheduler, kill-switch flag, logging setup and the
live-trading gate (ADR-0013).
"""

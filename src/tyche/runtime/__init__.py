"""The composition root: the one place that knows about both core and adapters.

Available now: ``tyche.runtime.data``, which wires the calendar, the Yahoo Finance
source, the Parquet cache and the clock together to fetch market data; and
``tyche.runtime.strategies``, which builds each configured strategy from its plugin.

Planned (Phase 1 onward): building an engine for a given mode by choosing the clock,
feed and broker; later the scheduler, kill-switch flag, logging setup and the
live-trading gate (ADR-0013).
"""

"""The composition root: the one place that knows about both core and adapters.

Available now: ``tyche.runtime.data``, which wires the calendar, the Yahoo Finance
source, the Parquet cache and the clock together to fetch market data;
``tyche.runtime.strategies``, which builds each configured strategy from its plugin;
and ``tyche.runtime.backtest``, which runs a backtest from the cache and writes its
run record (ADR-0024).

Planned (Phase 2 onward): building the engine for paper and live by choosing their
clock, feed and broker; the scheduler, kill-switch flag, logging setup and the
live-trading gate (ADR-0013).
"""

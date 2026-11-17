"""Stage 3, signals: the strategy plugin interface and the runner that calls plugins.

Planned (Phase 1): the ``Strategy`` protocol, the registry, and the runner that turns
market data into one ``SignalEvent`` per strategy per decision time. The plugins
themselves live in ``tyche.strategies`` (built in) or in the workspace.
"""

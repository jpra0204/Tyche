"""Simulation: vendor-free implementations of ports, built by us.

These are pure code, which is why they live in the core and not in ``tyche.adapters``.

Available now: ``SimClock``.

Planned (Phase 1): the historical replay feed, ``SimBroker`` and the fill, commission,
slippage and settlement models.
"""

from tyche.core.sim.clock import SimClock

__all__ = ["SimClock"]

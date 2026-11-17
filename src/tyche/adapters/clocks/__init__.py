"""``Clock`` adapters.

Available now: ``SystemClock``, the real time in UTC. The simulated clock is pure code
and lives in ``tyche.core.sim``.
"""

from tyche.adapters.clocks.system_clock import SystemClock

__all__ = ["SystemClock"]

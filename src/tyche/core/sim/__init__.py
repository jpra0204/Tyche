"""Simulation: vendor-free implementations of ports, built by us.

These are pure code, which is why they live in the core and not in ``tyche.adapters``.

Available now: ``SimClock``, ``HistoricalReplay`` (the backtest feed), ``SimBroker``
(the ``Broker`` port for backtests) and ``settlement_date`` (T+n on the trading
calendar). The commission, fee and slippage arithmetic is in
``tyche.core.domain.costs``.
"""

from tyche.core.sim.broker import (
    DEFAULT_MAX_VOLUME_PARTICIPATION,
    FreeRidingViolation,
    SimBroker,
    SimBrokerError,
)
from tyche.core.sim.clock import SimClock
from tyche.core.sim.replay import HistoricalReplay, cycle_id
from tyche.core.sim.settlement import settlement_date

__all__ = [
    "DEFAULT_MAX_VOLUME_PARTICIPATION",
    "FreeRidingViolation",
    "HistoricalReplay",
    "SimBroker",
    "SimBrokerError",
    "SimClock",
    "cycle_id",
    "settlement_date",
]

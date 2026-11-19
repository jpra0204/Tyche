"""Event types and the event bus.

Available now: the ``Event`` base class, the ``Envelope`` the bus wraps around every
event, the synchronous, deterministic ``EventBus`` (ADR-0003), the market events
(``SessionEvent``, ``BarEvent``, ``DataReadyEvent``, ``DataQualityEvent``),
``RunEvent``, the trading events (``ExecutionPlanEvent``, ``OrderEvent``,
``CancelRequestEvent``, ``FillEvent``, ``AccountEvent``, ``DistributionEvent``), and
the decision-cycle events (``UniverseEvent``, ``ScreeningEvent``, ``SignalEvent``,
``SignalsReadyEvent``, ``TargetPortfolioEvent``, ``ApprovedPortfolioEvent`` with its
``KEEP`` marker).

Planned (Phase 1 onward): the other events listed in
``docs/architecture/event-catalog.md``, each added by the PR that first publishes it.
"""

from tyche.core.events.bus import (
    BusError,
    BusHaltedError,
    EventBus,
    Handler,
    HandlerError,
    RunawayDispatchError,
)
from tyche.core.events.decision import (
    KEEP,
    ApprovedPortfolioEvent,
    Keep,
    ScreeningEvent,
    SignalEvent,
    SignalsReadyEvent,
    TargetPortfolioEvent,
    UniverseEvent,
)
from tyche.core.events.event import Envelope, Event
from tyche.core.events.market import (
    BarEvent,
    DataQualityEvent,
    DataReadyEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.events.system import RunEvent, RunMode, RunStage
from tyche.core.events.trading import (
    AccountEvent,
    CancelRequestEvent,
    DistributionEvent,
    ExecutionPlanEvent,
    FillEvent,
    OrderEvent,
)

__all__ = [
    "KEEP",
    "AccountEvent",
    "ApprovedPortfolioEvent",
    "BarEvent",
    "BusError",
    "BusHaltedError",
    "CancelRequestEvent",
    "DataQualityEvent",
    "DataReadyEvent",
    "DistributionEvent",
    "Envelope",
    "Event",
    "EventBus",
    "ExecutionPlanEvent",
    "FillEvent",
    "Handler",
    "HandlerError",
    "Keep",
    "OrderEvent",
    "RunEvent",
    "RunMode",
    "RunStage",
    "RunawayDispatchError",
    "ScreeningEvent",
    "SessionEvent",
    "SessionPhase",
    "SignalEvent",
    "SignalsReadyEvent",
    "TargetPortfolioEvent",
    "UniverseEvent",
]

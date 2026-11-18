"""Event types and the event bus.

Available now: the ``Event`` base class, the ``Envelope`` the bus wraps around every
event, the synchronous, deterministic ``EventBus`` (ADR-0003), the market events
(``SessionEvent``, ``BarEvent``, ``DataReadyEvent``, ``DataQualityEvent``),
``RunEvent``, the trading events (``OrderEvent``, ``FillEvent``,
``DistributionEvent``), and the first decision-cycle events (``UniverseEvent``,
``ScreeningEvent``).

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
from tyche.core.events.decision import ScreeningEvent, UniverseEvent
from tyche.core.events.event import Envelope, Event
from tyche.core.events.market import (
    BarEvent,
    DataQualityEvent,
    DataReadyEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.events.system import RunEvent, RunMode, RunStage
from tyche.core.events.trading import DistributionEvent, FillEvent, OrderEvent

__all__ = [
    "BarEvent",
    "BusError",
    "BusHaltedError",
    "DataQualityEvent",
    "DataReadyEvent",
    "DistributionEvent",
    "Envelope",
    "Event",
    "EventBus",
    "FillEvent",
    "Handler",
    "HandlerError",
    "OrderEvent",
    "RunEvent",
    "RunMode",
    "RunStage",
    "RunawayDispatchError",
    "ScreeningEvent",
    "SessionEvent",
    "SessionPhase",
    "UniverseEvent",
]

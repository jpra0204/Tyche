"""Event types and the event bus.

Available now: the ``Event`` base class, the ``Envelope`` the bus wraps around every
event, and the synchronous, deterministic ``EventBus`` (ADR-0003).

Planned (Phase 1 onward): the concrete events listed in
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
from tyche.core.events.event import Envelope, Event

__all__ = [
    "BusError",
    "BusHaltedError",
    "Envelope",
    "Event",
    "EventBus",
    "Handler",
    "HandlerError",
    "RunawayDispatchError",
]

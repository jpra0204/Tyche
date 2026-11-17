"""Ports: the interfaces the core uses to reach the outside world.

Each port is a ``typing.Protocol``. An implementation does not inherit from it; it only
has to provide the same methods. Implementations that touch the outside world live in
``tyche.adapters``; the simulated ones are pure code and live in ``tyche.core.sim``.

Available now: ``Clock``, ``Calendar`` and ``DataProvider``.

Planned (Phase 1 onward): ``Broker``, ``Notifier``, ``LLMProvider``
and the storage ports.
"""

from tyche.core.ports.calendar import Calendar, CalendarError, OutOfCalendarRangeError
from tyche.core.ports.clock import Clock
from tyche.core.ports.data import DataError, DataProvider

__all__ = [
    "Calendar",
    "CalendarError",
    "Clock",
    "DataError",
    "DataProvider",
    "OutOfCalendarRangeError",
]

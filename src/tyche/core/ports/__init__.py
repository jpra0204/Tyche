"""Ports: the interfaces the core uses to reach the outside world.

Each port is a ``typing.Protocol``. An implementation does not inherit from it; it only
has to provide the same methods. Implementations that touch the outside world live in
``tyche.adapters``; the simulated ones are pure code and live in ``tyche.core.sim``.

Available now: ``Clock`` and ``PacedClock``, ``Calendar``, ``DataProvider``, ``Feed``,
``Broker`` and ``JournalStore``.

Planned (Phase 2 onward): ``Notifier``, ``LLMProvider`` and the other storage ports.
"""

from tyche.core.ports.broker import Broker
from tyche.core.ports.calendar import Calendar, CalendarError, OutOfCalendarRangeError
from tyche.core.ports.clock import Clock, PacedClock
from tyche.core.ports.data import DataError, DataProvider
from tyche.core.ports.feed import Feed, FeedInput
from tyche.core.ports.journal import JournalStore, JournalStoreError

__all__ = [
    "Broker",
    "Calendar",
    "CalendarError",
    "Clock",
    "DataError",
    "DataProvider",
    "Feed",
    "FeedInput",
    "JournalStore",
    "JournalStoreError",
    "OutOfCalendarRangeError",
    "PacedClock",
]

"""Ports: the interfaces the core uses to reach the outside world.

Each port is a ``typing.Protocol``. An implementation does not inherit from it; it only
has to provide the same methods. Implementations that touch the outside world live in
``tyche.adapters``; the simulated ones are pure code and live in ``tyche.core.sim``.

Available now: ``Clock`` and ``PacedClock``, ``Calendar``, ``DataProvider``, ``Feed``,
``Broker``, ``JournalStore``, ``CheckpointStore``, ``KillSwitch`` and ``Notifier``
(with ``Alert``, ADR-0040).

Planned: ``LLMProvider`` and the other storage ports.
"""

from tyche.core.ports.broker import Broker
from tyche.core.ports.calendar import Calendar, CalendarError, OutOfCalendarRangeError
from tyche.core.ports.checkpoint import CheckpointStore, CheckpointStoreError
from tyche.core.ports.clock import Clock, PacedClock
from tyche.core.ports.data import DataError, DataProvider
from tyche.core.ports.feed import Feed, FeedInput
from tyche.core.ports.journal import JournalStore, JournalStoreError
from tyche.core.ports.kill_switch import KillSwitch
from tyche.core.ports.notifier import Alert, AlertKind, Notifier, NotifierError

__all__ = [
    "Alert",
    "AlertKind",
    "Broker",
    "Calendar",
    "CalendarError",
    "CheckpointStore",
    "CheckpointStoreError",
    "Clock",
    "DataError",
    "DataProvider",
    "Feed",
    "FeedInput",
    "JournalStore",
    "JournalStoreError",
    "KillSwitch",
    "Notifier",
    "NotifierError",
    "OutOfCalendarRangeError",
    "PacedClock",
]

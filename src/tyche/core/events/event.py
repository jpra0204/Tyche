"""The event base class and the envelope the bus wraps around every event."""

from dataclasses import dataclass
from datetime import datetime

from tyche.core.domain.validation import require_utc


class Event:
    """Base class for every event: an immutable record of something that happened.

    An event holds only its own facts (which bar, which order). The delivery details
    (sequence number, time, cause) are added by the bus in an ``Envelope``, so the
    component that creates an event cannot get them wrong.

    Subclasses must be frozen dataclasses and their names must end in ``Event``::

        @dataclass(frozen=True, slots=True)
        class FillEvent(Event):
            order_id: str
            quantity: Decimal

    The name rule is checked when the class is defined. Immutability is checked by the
    bus the first time an event of each type is published.
    """

    __slots__ = ()

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not cls.__name__.endswith("Event"):
            raise TypeError(f"event class {cls.__name__!r} must have a name ending in 'Event'")


@dataclass(frozen=True, slots=True)
class Envelope[E: Event]:
    """An event plus the facts about its delivery, assigned by the bus.

    Handlers receive envelopes. The journal stores them. Following ``caused_by`` back
    from any envelope answers "why did this happen?".

    Attributes:
        seq: Position in the run's event sequence, starting at 1. Events are handled
            in ``seq`` order, and the same inputs always produce the same sequence.
        occurred_at: Time on the clock when the event was published, in UTC. Simulated
            time in a backtest.
        source: Name of the component that published the event.
        event: The event itself.
        caused_by: ``seq`` of the event whose handler published this one, or ``None``
            for an input from outside (a bar from the feed, a message from the broker).
        cycle_id: The decision cycle this event belongs to, or ``None``. Inherited from
            the causing event unless the publisher sets it.
    """

    seq: int
    occurred_at: datetime
    source: str
    event: E
    caused_by: int | None = None
    cycle_id: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.occurred_at, f"envelope {self.seq}: occurred_at")

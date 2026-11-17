"""The Feed port: where the engine's inputs come from."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tyche.core.domain.validation import require_utc
from tyche.core.events import Event


@dataclass(frozen=True, slots=True)
class FeedInput:
    """One input from the outside world, and the moment it happens.

    Attributes:
        at: When the input becomes known, in UTC. The engine moves the clock here
            before publishing it, so nothing can see it earlier.
        event: What to publish.
        source: Who it comes from, recorded in the event's envelope.
        cycle_id: The decision cycle this input starts, if any.
    """

    at: datetime
    event: Event
    source: str
    cycle_id: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.at, "FeedInput at")


class Feed(Protocol):
    """A source of inputs in time order.

    In a backtest it replays history; in paper and live (Phase 2) it reports what
    arrives from the data source and the broker.
    """

    def inputs(self) -> Iterator[FeedInput]:
        """Yield inputs oldest first. Inputs at the same moment keep their order."""
        ...

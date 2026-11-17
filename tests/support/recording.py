"""Test helpers for observing what travels over an event bus."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from tyche.core.events import Envelope, Event, EventBus

START = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)


class TickingClock:
    """A fake time source: starts at ``START`` and advances one second per reading.

    Deterministic, so a test can assert exact timestamps.
    """

    def __init__(self, start: datetime = START, step: timedelta = timedelta(seconds=1)) -> None:
        self._next = start
        self._step = step

    def now(self) -> datetime:
        current = self._next
        self._next += self._step
        return current


class Recorder:
    """Subscribes to every event and keeps the envelopes in the order delivered."""

    def __init__(self, bus: EventBus, *, name: str = "recorder") -> None:
        self.envelopes: list[Envelope[Event]] = []
        bus.subscribe(Event, self.envelopes.append, name=name)

    def __iter__(self) -> Iterator[Envelope[Event]]:
        return iter(self.envelopes)

    def __len__(self) -> int:
        return len(self.envelopes)

    @property
    def events(self) -> list[Event]:
        return [envelope.event for envelope in self.envelopes]

    @property
    def trace(self) -> list[tuple[int, str, str, int | None, str | None]]:
        """A compact, comparable summary: (seq, event type, source, caused_by, cycle_id)."""
        return [
            (e.seq, type(e.event).__name__, e.source, e.caused_by, e.cycle_id)
            for e in self.envelopes
        ]

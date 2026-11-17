"""InMemoryJournal: every event of a run, kept in memory, in order."""

from typing import cast

from tyche.core.events import Envelope, Event, EventBus

SUBSCRIBER = "journal"


class InMemoryJournal:
    """Records every envelope the bus delivers, in delivery order.

    Subscribe it before anything is published (the bus refuses late subscribers). It is
    the in-memory half of pipeline stage 8; Phase 2 adds a journal stored in SQLite with
    the same subscription.
    """

    def __init__(self, bus: EventBus) -> None:
        self._entries: list[Envelope[Event]] = []
        self._by_seq: dict[int, Envelope[Event]] = {}
        bus.subscribe(Event, self._record, name=SUBSCRIBER)

    def _record(self, envelope: Envelope[Event]) -> None:
        self._entries.append(envelope)
        self._by_seq[envelope.seq] = envelope

    @property
    def entries(self) -> tuple[Envelope[Event], ...]:
        """Everything recorded, oldest first."""
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def of_type[E: Event](self, kind: type[E]) -> list[Envelope[E]]:
        """Recorded envelopes whose event is a ``kind`` (or a subclass of it)."""
        return [cast(Envelope[E], e) for e in self._entries if isinstance(e.event, kind)]

    def in_cycle(self, cycle_id: str) -> list[Envelope[Event]]:
        """Everything recorded for one decision cycle, in order."""
        return [e for e in self._entries if e.cycle_id == cycle_id]

    def causes_of(self, envelope: Envelope[Event]) -> list[Envelope[Event]]:
        """The chain from ``envelope`` back to the input that started it, newest first.

        This answers "why did this happen?": follow an order back through the approved
        target, the risk adjustments and the signals to the bar that triggered them.
        """
        chain = [envelope]
        current = envelope
        while current.caused_by is not None:
            current = self._by_seq[current.caused_by]
            chain.append(current)
        return chain

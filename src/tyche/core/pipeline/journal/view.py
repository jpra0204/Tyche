"""JournalView: one run's envelopes, searchable and traceable to their cause."""

from collections.abc import Iterable
from typing import cast

from tyche.core.events import Envelope, Event


class JournalView:
    """The questions any journal answers, over one run's envelopes in ``seq`` order.

    ``InMemoryJournal`` is a view that grows while the run goes on. A run read back from
    a ``JournalStore`` is a view too, built from ``store.read(run_id)``, so the same
    questions work on a run that ended days ago.
    """

    def __init__(self, entries: Iterable[Envelope[Event]] = ()) -> None:
        self._entries: list[Envelope[Event]] = []
        self._by_seq: dict[int, Envelope[Event]] = {}
        for envelope in entries:
            self._add(envelope)

    def _add(self, envelope: Envelope[Event]) -> None:
        if self._entries and envelope.seq <= self._entries[-1].seq:
            raise ValueError(
                f"journal entries must be in seq order: {envelope.seq} came after "
                f"{self._entries[-1].seq}"
            )
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

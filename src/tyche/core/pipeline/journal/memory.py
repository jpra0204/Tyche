"""InMemoryJournal: every event of a run, kept in memory, in order."""

from tyche.core.events import Envelope, Event, EventBus
from tyche.core.pipeline.journal.view import JournalView

SUBSCRIBER = "journal"


class InMemoryJournal(JournalView):
    """Records every envelope the bus delivers, in delivery order.

    Subscribe it before anything is published (the bus refuses late subscribers).
    Backtests use it: a research run is kept in its record, not in the workspace's
    state. ``StoredJournal`` is the durable half of pipeline stage 8, with the same
    subscription (ADR-0037).
    """

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        bus.subscribe(Event, self._record, name=SUBSCRIBER)

    def _record(self, envelope: Envelope[Event]) -> None:
        self._add(envelope)

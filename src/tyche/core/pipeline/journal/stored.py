"""StoredJournal: every event of a run, written to a JournalStore as it is delivered."""

from tyche.core.events import Envelope, Event, EventBus, RunEvent
from tyche.core.ports import JournalStore

SUBSCRIBER = "journal"


class StoredJournal:
    """Appends every envelope the bus delivers to ``store``, under ``run_id`` (ADR-0037).

    Subscribe it first, before any other stage, so that each event is stored before
    anything acts on it: if a handler then fails, the journal ends with the event that
    it failed on. A store that refuses an envelope raises, and the bus halts, because a
    run whose journal has a gap cannot explain what it did.

    The run id is given here, not read from the ``RunEvent``, so that the very first
    envelope is stored under the right run. A ``RunEvent`` for any other run is refused.
    """

    def __init__(self, bus: EventBus, store: JournalStore, run_id: str) -> None:
        if not run_id.strip():
            raise ValueError("StoredJournal needs a run id")
        self._store = store
        self._run_id = run_id
        self._count = 0
        bus.subscribe(Event, self._record, name=SUBSCRIBER)

    @property
    def run_id(self) -> str:
        return self._run_id

    def __len__(self) -> int:
        """How many envelopes this journal has stored for its run."""
        return self._count

    def _record(self, envelope: Envelope[Event]) -> None:
        event = envelope.event
        if isinstance(event, RunEvent) and event.run_id != self._run_id:
            raise ValueError(
                f"the journal stores run {self._run_id!r} but received a RunEvent for "
                f"run {event.run_id!r}"
            )
        self._store.append(self._run_id, envelope)
        self._count += 1

"""The JournalStore port: where the journal keeps every event of every run (ADR-0037)."""

from typing import Protocol

from tyche.core.events import Envelope, Event


class JournalStoreError(Exception):
    """The store refused an envelope, or could not read one back."""


class JournalStore(Protocol):
    """An append-only record of envelopes, one sequence per run.

    The store never changes or removes what it has accepted (ADR-0009). A run's
    envelopes are numbered from 1 by its bus, so the pair (run id, ``seq``) names one
    envelope for good, and ``caused_by`` always points to an earlier ``seq`` of the same
    run.
    """

    def append(self, run_id: str, envelope: Envelope[Event]) -> None:
        """Store ``envelope`` as part of ``run_id``, durably, before returning.

        Raises ``JournalStoreError`` if the run already has an envelope with that
        ``seq``, if its cause is not stored, or if the event cannot be stored.
        """
        ...

    def read(self, run_id: str) -> tuple[Envelope[Event], ...]:
        """Every envelope stored for ``run_id``, in ``seq`` order; empty if none."""
        ...

    def run_ids(self) -> tuple[str, ...]:
        """Every run with at least one stored envelope, oldest first."""
        ...

"""The CheckpointStore port: where each run leaves its state for the next (ADR-0038)."""

from typing import Protocol

from tyche.core.domain import Checkpoint


class CheckpointStoreError(Exception):
    """The store refused a checkpoint, or could not read one back."""


class CheckpointStore(Protocol):
    """An append-only record of checkpoints, one per run, in the order they were saved.

    A restart carries on from the latest. Earlier ones are kept, never changed: they
    say what state each run handed on (ADR-0009).
    """

    def save(self, checkpoint: Checkpoint) -> None:
        """Store ``checkpoint``, durably, before returning.

        Raises ``CheckpointStoreError`` if its run already has a checkpoint, if the
        run's journal is not stored, if it was taken no later than the latest one, or
        if it cannot be stored.
        """
        ...

    def latest(self) -> Checkpoint | None:
        """The checkpoint saved last, or ``None`` if there is none."""
        ...

    def read(self, run_id: str) -> Checkpoint | None:
        """The checkpoint ``run_id`` saved, or ``None`` if it saved none."""
        ...

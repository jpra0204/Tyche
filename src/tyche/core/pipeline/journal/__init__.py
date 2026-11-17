"""Stage 8, journal: record every decision with its reasons.

Available now: ``InMemoryJournal``, which subscribes to every event and can follow any
event back to the input that caused it.

Planned (Phase 2): a journal persisted in SQLite, read by reports, the Discord summary
and the weekly review.
"""

from tyche.core.pipeline.journal.memory import InMemoryJournal

__all__ = ["InMemoryJournal"]

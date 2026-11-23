"""Stage 8, journal: record every decision with its reasons.

Available now: ``InMemoryJournal``, which subscribes to every event and keeps a run in
memory (backtests use it); ``StoredJournal``, which writes every event to a
``JournalStore`` as it is delivered (ADR-0037); and ``JournalView``, which answers the
same questions over either, including a run read back from the store.

Planned (Phase 2): the paper cycle stores its journal; the Discord summary and the
weekly review read it.
"""

from tyche.core.pipeline.journal.memory import InMemoryJournal
from tyche.core.pipeline.journal.stored import StoredJournal
from tyche.core.pipeline.journal.view import JournalView

__all__ = ["InMemoryJournal", "JournalView", "StoredJournal"]

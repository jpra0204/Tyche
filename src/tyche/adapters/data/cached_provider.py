"""A ``DataProvider`` that serves bars from the Parquet cache and fetches only what is missing.

This is a read-through cache: the caller asks for a range of sessions, the provider
answers from the cache, asks the source for sessions it has not covered yet, stores
what comes back, and audits the result against the trading calendar.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

from tyche.adapters.data.parquet_cache import CacheEntry, DateRange, ParquetBarCache
from tyche.core.domain import (
    DEFAULT_MAX_DAILY_MOVE,
    Bar,
    BarHistory,
    DataIssue,
    DataIssueKind,
    Instrument,
    Session,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.ports import Calendar, Clock, DataError

# Found again from the cache on every request, so a fetch must not report them a second time.
_REDERIVED = frozenset({DataIssueKind.MISSING_SESSION, DataIssueKind.SUSPECT_MOVE})


class BarSource(Protocol):
    """A vendor of raw daily bars, such as yfinance (PR 6).

    Sources are adapter-level: the core never sees one. A source returns bars already
    converted to ``Bar`` objects, each stamped at its session's close in UTC.
    """

    @property
    def name(self) -> str:
        """Short lower-case name, used as the cache folder, e.g. ``yfinance``."""
        ...

    @property
    def adjusted(self) -> bool:
        """Whether the bars this source returns are adjusted for splits and dividends."""
        ...

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> Sequence[Bar]:
        """Return whatever bars the source has for sessions from ``first`` to ``last``.

        Raises:
            DataError: The source could not be reached or answered with an error.
        """
        ...


class CachedDataProvider:
    """Implements ``DataProvider`` on top of a ``BarSource`` and a ``ParquetBarCache``.

    Coverage rule: after a fetch, the sessions from the start of the request through
    the last session the source returned a bar for are marked as covered and are not
    asked for again. Sessions after the last returned bar stay uncovered, because the
    source may simply not have published them yet. A gap in the middle stays a gap:
    asking again would not change the answer.

    Args:
        source: Where missing bars come from.
        cache: Where bars are kept between runs. Its source name must match.
        calendars: Calendar for each calendar code an instrument may use.
        clock: Decides which sessions have closed, and stamps each fetch.
        max_move: Close-to-close change flagged as suspect by the audit.
    """

    def __init__(
        self,
        source: BarSource,
        cache: ParquetBarCache,
        calendars: Mapping[str, Calendar],
        clock: Clock,
        *,
        max_move: float = DEFAULT_MAX_DAILY_MOVE,
    ) -> None:
        if cache.source != source.name:
            raise ValueError(
                f"cache is for source {cache.source!r} but the source is {source.name!r}"
            )
        self._source = source
        self._cache = cache
        self._calendars = dict(calendars)
        self._clock = clock
        self._max_move = max_move

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        sessions = self._closed_sessions(instrument, first, last)
        if not sessions:
            return BarHistory(instrument, ())

        entry = self._cache.load(instrument, Timeframe.D1)
        fetch_issues: tuple[DataIssue, ...] = ()
        uncovered = [session for session in sessions if not entry.covers(session.day)]
        if uncovered:
            entry, fetch_issues = self._fetch(instrument, entry, sessions, uncovered)

        rows = entry.bars_between(sessions[0].opens_at, sessions[-1].closes_at)
        is_adjusted = self._source.adjusted if entry.is_adjusted is None else entry.is_adjusted
        audited = audit_daily_bars(
            instrument,
            (row.bar for row in rows),
            sessions,
            adjusted=is_adjusted,
            max_move=self._max_move,
        )
        # The fetch adds only what it dropped before caching; the rest is found again above.
        dropped = tuple(i for i in fetch_issues if i.kind not in _REDERIVED)
        fetched_times = [row.fetched_at for row in rows]
        return BarHistory(
            instrument,
            audited.bars,
            dropped + audited.issues,
            (min(fetched_times), max(fetched_times)) if fetched_times else None,
        )

    def _closed_sessions(self, instrument: Instrument, first: date, last: date) -> list[Session]:
        calendar = self._calendars.get(instrument.calendar)
        if calendar is None:
            raise DataError(f"no calendar {instrument.calendar!r} loaded for {instrument}")
        now = self._clock.now()
        return [s for s in calendar.sessions_between(first, last) if s.closes_at <= now]

    def _fetch(
        self,
        instrument: Instrument,
        entry: CacheEntry,
        sessions: Sequence[Session],
        uncovered: Sequence[Session],
    ) -> tuple[CacheEntry, tuple[DataIssue, ...]]:
        fetch_first, fetch_last = uncovered[0].day, uncovered[-1].day
        raw = self._source.fetch_daily(instrument, fetch_first, fetch_last)
        window = [s for s in sessions if fetch_first <= s.day <= fetch_last]
        audited = audit_daily_bars(
            instrument,
            raw,
            window,
            adjusted=self._source.adjusted,
            max_move=self._max_move,
        )

        if not audited.bars:
            # Nothing usable came back: cover nothing, store nothing, ask again next time.
            return entry, audited.issues

        last_returned = audited.bars[-1].timestamp
        through = max(s.day for s in window if s.closes_at <= last_returned)
        updated = entry.merged(
            audited.bars,
            fetched_at=self._clock.now(),
            covered=DateRange(fetch_first, through),
            is_adjusted=self._source.adjusted,
        )
        self._cache.store(updated)
        return updated, audited.issues

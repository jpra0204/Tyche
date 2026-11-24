"""A ``DataProvider`` that serves bars from the Parquet cache and fetches only what is missing.

This is a read-through cache: the caller asks for a range of sessions, the provider
answers from the cache, asks the source for sessions it has not covered yet, stores
what comes back, and audits the result against the trading calendar.

Prices are cached adjusted for splits only, and dividends are kept as separate cash
events (ADR-0019). A split rewrites every earlier price, so when a fetch reveals a
split the cache has not seen, and the cache holds bars from before it, the
instrument's whole history is fetched again.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

from tyche.adapters.data.parquet_cache import CacheEntry, DateRange, ParquetBarCache
from tyche.core.domain import (
    DEFAULT_MAX_DAILY_MOVE,
    Bar,
    BarHistory,
    CashDistribution,
    DataIssue,
    DataIssueKind,
    Instrument,
    PriceAdjustment,
    Session,
    Split,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.ports import Calendar, Clock, DataError

# Found again from the cache on every request, so a fetch must not report them twice.
_REDERIVED = frozenset({DataIssueKind.MISSING_SESSION, DataIssueKind.SUSPECT_MOVE})


@dataclass(frozen=True, slots=True)
class SourceData:
    """What a ``BarSource`` returns for one request.

    Attributes:
        bars: Bars the source sent, stamped at session closes in UTC where possible.
        distributions: Cash distributions with an ex-date in the requested range.
        splits: Splits with an ex-date in the requested range.
        issues: Problems the source found while converting its data, such as a row
            whose prices cannot be real. Those rows are not in ``bars``.
    """

    bars: tuple[Bar, ...] = ()
    distributions: tuple[CashDistribution, ...] = ()
    splits: tuple[Split, ...] = ()
    issues: tuple[DataIssue, ...] = ()


class BarSource(Protocol):
    """A vendor of daily bars and corporate actions, such as yfinance.

    Sources are adapter-level: the core never sees one.
    """

    @property
    def name(self) -> str:
        """Short lower-case name, used as the cache folder, e.g. ``yfinance``."""
        ...

    @property
    def adjustment(self) -> PriceAdjustment:
        """How the prices this source returns are adjusted."""
        ...

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        """Return what the source has for sessions from ``first`` to ``last``.

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

    An empty answer covers nothing, with one exception: when the request ends before
    the earliest bar already cached, the source has nothing for those sessions because
    the instrument did not exist yet (GLD before November 2004), and asking again will
    not change that. The request is then covered, and the audit keeps reporting its
    sessions as missing.

    Args:
        source: Where missing bars come from.
        cache: Where bars are kept between runs. Its source name must match.
        calendars: Calendar for each calendar code an instrument may use.
        clock: Decides which sessions have closed, and stamps each fetch.
        max_move: Close-to-close change flagged as suspect by the audit.
        after_close: How long after a session's close its bars count as final
            (ADR-0043). Until then the session is treated as not closed: it is neither
            asked for nor expected, so a provisional bar can never enter the cache,
            where it would stay. The workspace gives the market profile's
            ``daily_cycle.after_close``; zero treats a session as final at its close.
    """

    def __init__(
        self,
        source: BarSource,
        cache: ParquetBarCache,
        calendars: Mapping[str, Calendar],
        clock: Clock,
        *,
        max_move: float = DEFAULT_MAX_DAILY_MOVE,
        after_close: timedelta = timedelta(0),
    ) -> None:
        if after_close < timedelta(0):
            raise ValueError(f"after_close must not be negative, got {after_close}")
        if cache.source != source.name:
            raise ValueError(
                f"cache is for source {cache.source!r} but the source is {source.name!r}"
            )
        self._source = source
        self._cache = cache
        self._calendars = dict(calendars)
        self._clock = clock
        self._max_move = max_move
        self._after_close = after_close

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        calendar = self._calendar_for(instrument)
        sessions = self._closed_sessions(calendar, first, last)
        if not sessions:
            return BarHistory(instrument, ())

        entry = self._cache.load(instrument, Timeframe.D1)
        fetch_issues: tuple[DataIssue, ...] = ()
        uncovered = [session for session in sessions if not entry.covers(session.day)]
        if uncovered:
            entry, fetch_issues = self._fetch(
                instrument, calendar, entry, uncovered[0].day, uncovered[-1].day
            )

        rows = entry.bars_between(sessions[0].opens_at, sessions[-1].closes_at)
        audited = audit_daily_bars(
            instrument,
            (row.bar for row in rows),
            sessions,
            adjustment=entry.adjustment or self._source.adjustment,
            max_move=self._max_move,
        )
        # The fetch adds only what it dropped before caching; the rest is found again above.
        dropped = tuple(i for i in fetch_issues if i.kind not in _REDERIVED)
        fetched_times = [row.fetched_at for row in rows]
        first_day, last_day = sessions[0].day, sessions[-1].day
        return BarHistory(
            instrument,
            audited.bars,
            issues=dropped + audited.issues,
            distributions=entry.distributions_between(first_day, last_day),
            splits=entry.splits_between(first_day, last_day),
            fetched=(min(fetched_times), max(fetched_times)) if fetched_times else None,
        )

    def _calendar_for(self, instrument: Instrument) -> Calendar:
        calendar = self._calendars.get(instrument.calendar)
        if calendar is None:
            raise DataError(f"no calendar {instrument.calendar!r} loaded for {instrument}")
        return calendar

    def _closed_sessions(self, calendar: Calendar, first: date, last: date) -> list[Session]:
        final_by = self._clock.now() - self._after_close
        return [s for s in calendar.sessions_between(first, last) if s.closes_at <= final_by]

    def _fetch(
        self,
        instrument: Instrument,
        calendar: Calendar,
        entry: CacheEntry,
        first: date,
        last: date,
    ) -> tuple[CacheEntry, tuple[DataIssue, ...]]:
        data = self._source.fetch_daily(instrument, first, last)

        if self._invalidated_by_new_split(entry, data.splits, calendar):
            # Every cached price from before the split is on the old basis. Start again.
            first = entry.coverage[0].first
            last = max(last, entry.coverage[-1].last)
            data = self._source.fetch_daily(instrument, first, last)
            if not data.bars:
                raise DataError(
                    f"{instrument} has a new split, but the source returned no bars when "
                    f"its full history ({first} to {last}) was requested again"
                )
            entry = CacheEntry(instrument, Timeframe.D1)

        window = self._closed_sessions(calendar, first, last)
        audited = audit_daily_bars(
            instrument,
            data.bars,
            window,
            adjustment=self._source.adjustment,
            max_move=self._max_move,
        )
        issues = data.issues + audited.issues
        if not data.bars and self._ends_before_first_cached_bar(entry, window):
            # Nothing exists this early. Record that it was asked, so it is not asked again.
            updated = entry.merged(
                (),
                fetched_at=self._clock.now(),
                covered=DateRange(first, last),
                adjustment=self._source.adjustment,
                distributions=data.distributions,
                splits=data.splits,
            )
            self._cache.store(updated)
            return updated, issues
        if not audited.bars:
            # Nothing usable came back: cover nothing, store nothing, ask again next time.
            return entry, issues

        last_returned = audited.bars[-1].timestamp
        through = max(s.day for s in window if s.closes_at <= last_returned)
        updated = entry.merged(
            audited.bars,
            fetched_at=self._clock.now(),
            covered=DateRange(first, through),
            adjustment=self._source.adjustment,
            distributions=data.distributions,
            splits=data.splits,
        )
        self._cache.store(updated)
        return updated, issues

    @staticmethod
    def _ends_before_first_cached_bar(entry: CacheEntry, window: Sequence[Session]) -> bool:
        """True if every session in ``window`` closed before the earliest cached bar."""
        if not entry.rows or not window:
            return False
        return window[-1].closes_at < entry.rows[0].bar.timestamp

    @staticmethod
    def _invalidated_by_new_split(
        entry: CacheEntry, splits: Sequence[Split], calendar: Calendar
    ) -> bool:
        known = set(entry.splits)
        for split in splits:
            if split in known:
                continue
            session = calendar.session_on(split.ex_date)
            cutoff = (
                session.opens_at
                if session is not None
                else datetime.combine(split.ex_date, time.min, tzinfo=UTC)
            )
            if any(row.bar.timestamp < cutoff for row in entry.rows):
                return True
        return False

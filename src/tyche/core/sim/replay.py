"""HistoricalReplay: a ``Feed`` that plays cached history back in time order.

For each trading session, inputs are produced in this order::

    session open                      at the open
    one BarEvent per instrument       at the close
    any DataQualityEvent for the day  at the close
    session close                     at the close
    DataReadyEvent (starts a cycle)   at the close

A bar is published at its own timestamp, its session's close, and never earlier. The
engine moves the clock to each input's moment before publishing it, so no subscriber
can see a bar before it was known. This is how the replay prevents lookahead.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from tyche.core.domain import Bar, BarHistory, DataIssue, Instrument, Session, Timeframe
from tyche.core.events import (
    BarEvent,
    DataQualityEvent,
    DataReadyEvent,
    Event,
    SessionEvent,
    SessionPhase,
)
from tyche.core.ports import Calendar, FeedInput

SOURCE_CALENDAR = "calendar"
SOURCE_REPLAY = "replay"

# Order of inputs that share a moment.
_EARLY_ISSUE, _OPEN, _BAR, _QUALITY, _CLOSE, _READY = range(6)


def cycle_id(session: Session) -> str:
    """The identifier of the decision cycle that starts at ``session``'s close."""
    return f"{session.calendar}:{session.day.isoformat()}:1d"


@dataclass(frozen=True, slots=True)
class _Scheduled:
    rank: int
    sequence: int
    item: FeedInput


class HistoricalReplay:
    """Replays daily ``BarHistory`` objects through the sessions of their calendars.

    Implements the ``Feed`` port.

    Args:
        histories: One audited history per instrument, in the order instruments should
            be published within a session.
        calendars: A calendar for every calendar code the instruments use.
        first: First session day to replay.
        last: Last session day to replay.

    Data issues are replayed too: those tied to a session at that session's close, and
    those with no session (bars dropped before caching) before the first session opens.
    Bars outside the range are not replayed.
    """

    def __init__(
        self,
        histories: Sequence[BarHistory],
        calendars: Mapping[str, Calendar],
        first: date,
        last: date,
    ) -> None:
        if first > last:
            raise ValueError(f"empty replay range: {first} is after {last}")
        instruments = [history.instrument for history in histories]
        if len(set(instruments)) != len(instruments):
            raise ValueError("each instrument may appear in only one history")
        unloaded = {i.calendar for i in instruments} - set(calendars)
        if unloaded:
            raise ValueError(f"no calendar loaded for {', '.join(sorted(unloaded))}")

        self._scheduled: list[_Scheduled] = []
        by_calendar: dict[str, list[BarHistory]] = {}
        for history in histories:
            by_calendar.setdefault(history.instrument.calendar, []).append(history)
        for code, members in by_calendar.items():
            for session in calendars[code].sessions_between(first, last):
                self._schedule_session(session, members)

        sessionless = [issue for h in histories for issue in h.issues if issue.session_day is None]
        if self._scheduled and sessionless:
            earliest = min(s.item.at for s in self._scheduled)
            for issue in sessionless:
                self._add(earliest, _EARLY_ISSUE, DataQualityEvent(issue), SOURCE_REPLAY)

        self._scheduled.sort(key=lambda s: (s.item.at, s.rank, s.sequence))

    @property
    def start(self) -> datetime | None:
        """The moment of the first input, or ``None`` if there are none."""
        return self._scheduled[0].item.at if self._scheduled else None

    def inputs(self) -> Iterator[FeedInput]:
        for scheduled in self._scheduled:
            yield scheduled.item

    def _add(
        self, at: datetime, rank: int, event: Event, source: str, cycle: str | None = None
    ) -> None:
        item = FeedInput(at, event, source, cycle)
        self._scheduled.append(_Scheduled(rank, len(self._scheduled), item))

    def _schedule_session(self, session: Session, members: Sequence[BarHistory]) -> None:
        close = session.closes_at
        self._add(
            session.opens_at, _OPEN, SessionEvent(session, SessionPhase.OPEN), SOURCE_CALENDAR
        )

        delivered: list[Instrument] = []
        missing: list[Instrument] = []
        for history in members:
            bar = _bar_at(history.bars, close)
            if bar is None:
                missing.append(history.instrument)
            else:
                delivered.append(history.instrument)
                self._add(close, _BAR, BarEvent(bar), SOURCE_REPLAY)

        issues: list[DataIssue] = [
            issue for h in members for issue in h.issues if issue.session_day == session.day
        ]
        for issue in issues:
            self._add(close, _QUALITY, DataQualityEvent(issue), SOURCE_REPLAY)

        self._add(close, _CLOSE, SessionEvent(session, SessionPhase.CLOSE), SOURCE_CALENDAR)
        ready = DataReadyEvent(Timeframe.D1, close, tuple(delivered), tuple(missing))
        self._add(close, _READY, ready, SOURCE_REPLAY, cycle_id(session))


def _bar_at(bars: Sequence[Bar], moment: datetime) -> Bar | None:
    # Histories are short enough for daily data that a scan is fine; an index can come later.
    for bar in bars:
        if bar.timestamp == moment:
            return bar
    return None

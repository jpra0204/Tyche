"""BarHistory: checked daily bars for one instrument, plus every problem found.

Free market data is unreliable (brief, section 4.5). Rather than trusting it or
rejecting it outright, Tyche audits it against the trading calendar: bars that cannot
be right are dropped, doubtful ones are kept and flagged, and every finding is
returned beside the bars so it can be reported. Nothing is silently fixed.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from itertools import pairwise

from tyche.core.domain.bar import Bar
from tyche.core.domain.instrument import Instrument
from tyche.core.domain.session import Session
from tyche.core.domain.timeframe import Timeframe
from tyche.core.domain.validation import require_utc

DEFAULT_MAX_DAILY_MOVE = 0.5
"""Close-to-close change, as a fraction, beyond which a bar is flagged as suspect.

50% in one session is possible (a crash, a buyout) but rare for the ETFs and large
stocks Tyche starts with, and far more often a data error such as a missed split.
"""


class DataIssueKind(StrEnum):
    """What was wrong. Each kind says whether the bar involved was kept."""

    MISSING_SESSION = "missing_session"
    """The market was open but there is no bar. Nothing to drop."""

    OFF_SESSION = "off_session"
    """A bar is not stamped at a session close. Dropped."""

    DUPLICATE = "duplicate"
    """The same bar appears more than once. One copy kept."""

    CONFLICT = "conflict"
    """Different bars claim the same session. All dropped: there is no telling which is right."""

    WRONG_SERIES = "wrong_series"
    """A bar belongs to another instrument or timeframe. Dropped."""

    MIXED_ADJUSTMENT = "mixed_adjustment"
    """A bar is adjusted when the others are not, or the reverse. Dropped."""

    SUSPECT_MOVE = "suspect_move"
    """The close moved more than the threshold since the previous bar. Kept, flagged."""


@dataclass(frozen=True, slots=True)
class DataIssue:
    """One problem found in market data.

    Attributes:
        kind: What was wrong.
        instrument: Whose data it was.
        session_day: The session concerned, when there is one.
        detail: A sentence a person can act on.
    """

    kind: DataIssueKind
    instrument: Instrument
    session_day: date | None
    detail: str

    def __str__(self) -> str:
        day = f" {self.session_day.isoformat()}" if self.session_day else ""
        return f"{self.instrument}{day} {self.kind}: {self.detail}"


@dataclass(frozen=True, slots=True)
class BarHistory:
    """Daily bars for one instrument, oldest first, after an audit.

    Construction guarantees the bars are usable together: one instrument, the daily
    timeframe, one adjustment basis, strictly increasing timestamps. Problems the audit
    found are in ``issues``; an empty tuple means none.

    Attributes:
        instrument: Whose bars these are.
        bars: The bars that passed the audit, oldest first.
        issues: Every problem found, in session order.
        fetched: Oldest and newest time any of these bars was fetched from its source,
            in UTC, or ``None`` if unknown. A backtest report states it, because free
            data sources revise history.
    """

    instrument: Instrument
    bars: tuple[Bar, ...]
    issues: tuple[DataIssue, ...] = ()
    fetched: tuple[datetime, datetime] | None = None

    def __post_init__(self) -> None:
        label = f"BarHistory for {self.instrument}"
        previous: Bar | None = None
        for bar in self.bars:
            if bar.instrument != self.instrument or bar.timeframe is not Timeframe.D1:
                raise ValueError(f"{label} holds a bar of {bar.instrument} {bar.timeframe}")
            if previous is not None:
                if bar.timestamp <= previous.timestamp:
                    raise ValueError(f"{label}: bars must be strictly increasing in time")
                if bar.is_adjusted != previous.is_adjusted:
                    raise ValueError(f"{label}: bars mix adjusted and unadjusted prices")
            previous = bar
        if self.fetched is not None:
            oldest, newest = self.fetched
            require_utc(oldest, "BarHistory fetched (oldest)")
            require_utc(newest, "BarHistory fetched (newest)")
            if oldest > newest:
                raise ValueError("BarHistory fetched: oldest is after newest")

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def issues_of(self, kind: DataIssueKind) -> tuple[DataIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind is kind)


def audit_daily_bars(
    instrument: Instrument,
    bars: Iterable[Bar],
    sessions: Sequence[Session],
    *,
    adjusted: bool,
    max_move: float = DEFAULT_MAX_DAILY_MOVE,
) -> BarHistory:
    """Check daily bars against the sessions they should cover.

    Args:
        instrument: The instrument the bars should belong to.
        bars: Bars in any order, possibly with problems.
        sessions: The sessions expected to have a bar, oldest first. They define the
            window: bars stamped before the first session's open or after the last
            session's close are outside it and ignored without an issue.
        adjusted: Whether the bars should be adjusted for splits and dividends.
        max_move: Close-to-close change beyond which a bar is flagged as suspect.

    Returns:
        A ``BarHistory`` with the bars that passed and every issue found.
    """
    if max_move <= 0:
        raise ValueError("max_move must be positive")
    if not sessions:
        return BarHistory(instrument, ())

    by_close = {session.closes_at: session for session in sessions}
    window_start = sessions[0].opens_at
    window_end = sessions[-1].closes_at
    issues: list[tuple[datetime, DataIssue]] = []

    def report(kind: DataIssueKind, when: datetime, day: date | None, detail: str) -> None:
        issues.append((when, DataIssue(kind, instrument, day, detail)))

    candidates: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in bars:
        if not window_start <= bar.timestamp <= window_end:
            continue
        if bar.instrument != instrument or bar.timeframe is not Timeframe.D1:
            report(
                DataIssueKind.WRONG_SERIES,
                bar.timestamp,
                None,
                f"dropped a {bar.timeframe} bar of {bar.instrument} at {bar.timestamp.isoformat()}",
            )
            continue
        if bar.is_adjusted != adjusted:
            expected = "adjusted" if adjusted else "unadjusted"
            report(
                DataIssueKind.MIXED_ADJUSTMENT,
                bar.timestamp,
                None,
                f"dropped a bar at {bar.timestamp.isoformat()} that is not {expected}",
            )
            continue
        if bar.timestamp not in by_close:
            report(
                DataIssueKind.OFF_SESSION,
                bar.timestamp,
                None,
                f"dropped a bar at {bar.timestamp.isoformat()}, which is not a session close",
            )
            continue
        candidates[bar.timestamp].append(bar)

    kept: list[Bar] = []
    for session in sessions:
        found = candidates.get(session.closes_at, [])
        if not found:
            report(
                DataIssueKind.MISSING_SESSION,
                session.closes_at,
                session.day,
                "no bar for this session",
            )
            continue
        distinct = set(found)
        if len(distinct) > 1:
            report(
                DataIssueKind.CONFLICT,
                session.closes_at,
                session.day,
                f"dropped {len(found)} different bars for the same session",
            )
            continue
        if len(found) > 1:
            report(
                DataIssueKind.DUPLICATE,
                session.closes_at,
                session.day,
                f"kept one of {len(found)} identical bars",
            )
        kept.append(found[0])

    for previous, bar in pairwise(kept):
        move = bar.close / previous.close - 1
        if abs(move) > max_move:
            day = by_close[bar.timestamp].day
            report(
                DataIssueKind.SUSPECT_MOVE,
                bar.timestamp,
                day,
                f"close moved {move:+.1%} from {previous.close} to {bar.close}; "
                "check for a split or a bad price",
            )

    ordered = tuple(issue for _, issue in sorted(issues, key=lambda pair: pair[0]))
    return BarHistory(instrument, tuple(kept), ordered)

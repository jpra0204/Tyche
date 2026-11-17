"""The data-quality audit: drop what cannot be right, flag what is doubtful, report everything."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of, session
from tyche.core.domain import (
    DEFAULT_MAX_DAILY_MOVE,
    Bar,
    BarHistory,
    DataIssue,
    DataIssueKind,
    Timeframe,
    audit_daily_bars,
)

DAYS = JANUARY_2024[:5]  # 2, 3, 4, 5 and 8 January
SESSIONS = [session(day) for day in DAYS]


def audit(bars: Iterable[Bar], *, max_move: float = DEFAULT_MAX_DAILY_MOVE) -> BarHistory:
    return audit_daily_bars(SPY, bars, SESSIONS, adjusted=True, max_move=max_move)


def kinds(history: BarHistory) -> list[DataIssueKind]:
    return [issue.kind for issue in history.issues]


class TestCleanData:
    def test_one_bar_per_session_passes_with_no_issues(self) -> None:
        history = audit([bar(day) for day in DAYS])

        assert len(history.bars) == 5
        assert not history.has_issues
        assert history.issues == ()

    def test_bars_come_back_oldest_first_whatever_the_input_order(self) -> None:
        history = audit([bar(day) for day in reversed(DAYS)])

        assert [b.timestamp for b in history.bars] == [close_of(day) for day in DAYS]

    def test_no_sessions_means_an_empty_history(self) -> None:
        history = audit_daily_bars(SPY, [bar(DAYS[0])], [], adjusted=True)

        assert history.bars == ()
        assert history.issues == ()

    def test_bars_outside_the_window_are_ignored_without_an_issue(self) -> None:
        before = bar(date(2023, 12, 29))
        after = bar(date(2024, 1, 9))

        history = audit([before, *(bar(day) for day in DAYS), after])

        assert len(history.bars) == 5
        assert not history.has_issues


class TestDropped:
    def test_a_missing_session_is_reported(self) -> None:
        history = audit([bar(day) for day in DAYS if day != date(2024, 1, 4)])

        assert kinds(history) == [DataIssueKind.MISSING_SESSION]
        assert history.issues[0].session_day == date(2024, 1, 4)
        assert len(history.bars) == 4

    def test_a_bar_off_the_session_close_is_dropped(self) -> None:
        midnight = datetime(2024, 1, 4, 0, 0, tzinfo=UTC)  # how some vendors stamp daily bars
        bars = [bar(day) for day in DAYS if day != date(2024, 1, 4)]

        history = audit([*bars, bar(date(2024, 1, 4), timestamp=midnight)])

        assert kinds(history) == [DataIssueKind.OFF_SESSION, DataIssueKind.MISSING_SESSION]
        assert "not a session close" in history.issues[0].detail

    def test_identical_duplicates_keep_one_copy(self) -> None:
        history = audit([*(bar(day) for day in DAYS), bar(date(2024, 1, 3))])

        assert kinds(history) == [DataIssueKind.DUPLICATE]
        assert len(history.bars) == 5

    def test_conflicting_bars_for_one_session_are_all_dropped(self) -> None:
        conflicting = bar(date(2024, 1, 3), close=105.0)

        history = audit([*(bar(day) for day in DAYS), conflicting])

        assert kinds(history) == [DataIssueKind.CONFLICT]
        assert history.issues[0].session_day == date(2024, 1, 3)
        assert date(2024, 1, 3) not in [b.timestamp.date() for b in history.bars]

    @pytest.mark.parametrize(
        "stray",
        [
            bar(date(2024, 1, 3), instrument=QQQ),
            bar(date(2024, 1, 3), timeframe=Timeframe.H1),
        ],
        ids=["other instrument", "other timeframe"],
    )
    def test_a_bar_from_another_series_is_dropped(self, stray: Bar) -> None:
        history = audit([*(bar(day) for day in DAYS), stray])

        assert kinds(history) == [DataIssueKind.WRONG_SERIES]
        assert len(history.bars) == 5

    def test_a_bar_with_the_other_adjustment_is_dropped(self) -> None:
        bars = [bar(day) for day in DAYS if day != date(2024, 1, 5)]

        history = audit([*bars, bar(date(2024, 1, 5), adjusted=False)])

        assert kinds(history) == [DataIssueKind.MIXED_ADJUSTMENT, DataIssueKind.MISSING_SESSION]
        assert "not adjusted" in history.issues[0].detail


class TestSuspectMoves:
    def test_a_large_jump_is_flagged_but_kept(self) -> None:
        closes = [100.0, 101.0, 260.0, 262.0, 263.0]  # looks like a missed reverse split

        history = audit([bar(day, close) for day, close in zip(DAYS, closes, strict=True)])

        assert kinds(history) == [DataIssueKind.SUSPECT_MOVE]
        assert history.issues[0].session_day == date(2024, 1, 4)
        assert "+157.4%" in history.issues[0].detail
        assert len(history.bars) == 5

    def test_a_large_fall_is_flagged(self) -> None:
        closes = [100.0, 40.0, 40.0, 40.0, 40.0]

        history = audit([bar(day, close) for day, close in zip(DAYS, closes, strict=True)])

        assert kinds(history) == [DataIssueKind.SUSPECT_MOVE]
        assert "-60.0%" in history.issues[0].detail

    def test_the_threshold_is_configurable_and_not_inclusive(self) -> None:
        closes = [100.0, 110.0, 110.0, 110.0, 110.0]  # +10%
        bars = [bar(day, close) for day, close in zip(DAYS, closes, strict=True)]

        assert kinds(audit(bars, max_move=0.05)) == [DataIssueKind.SUSPECT_MOVE]
        assert kinds(audit(bars, max_move=0.11)) == []

    def test_the_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_move must be positive"):
            audit([], max_move=0)


def test_issues_are_reported_in_time_order() -> None:
    closes = {date(2024, 1, 2): 100.0, date(2024, 1, 4): 300.0, date(2024, 1, 8): 300.0}

    history = audit([bar(day, close) for day, close in closes.items()])

    assert [(i.kind, i.session_day) for i in history.issues] == [
        (DataIssueKind.MISSING_SESSION, date(2024, 1, 3)),
        (DataIssueKind.SUSPECT_MOVE, date(2024, 1, 4)),
        (DataIssueKind.MISSING_SESSION, date(2024, 1, 5)),
    ]
    assert history.issues_of(DataIssueKind.MISSING_SESSION) == (
        history.issues[0],
        history.issues[2],
    )


def test_an_issue_reads_as_a_sentence() -> None:
    issue = DataIssue(
        DataIssueKind.MISSING_SESSION, SPY, date(2024, 1, 4), "no bar for this session"
    )

    assert str(issue) == "SPY@ARCX 2024-01-04 missing_session: no bar for this session"


class TestBarHistoryRules:
    def test_rejects_a_bar_of_another_instrument(self) -> None:
        with pytest.raises(ValueError, match="holds a bar of QQQ@XNAS"):
            BarHistory(SPY, (bar(DAYS[0], instrument=QQQ),))

    def test_rejects_an_intraday_bar(self) -> None:
        with pytest.raises(ValueError, match="1h"):
            BarHistory(SPY, (bar(DAYS[0], timeframe=Timeframe.H1),))

    def test_rejects_bars_out_of_order_or_repeated(self) -> None:
        with pytest.raises(ValueError, match="strictly increasing"):
            BarHistory(SPY, (bar(DAYS[1]), bar(DAYS[0])))
        with pytest.raises(ValueError, match="strictly increasing"):
            BarHistory(SPY, (bar(DAYS[0]), bar(DAYS[0])))

    def test_rejects_mixed_adjustment(self) -> None:
        with pytest.raises(ValueError, match="mix adjusted and unadjusted"):
            BarHistory(SPY, (bar(DAYS[0]), bar(DAYS[1], adjusted=False)))

    def test_fetched_range_must_be_utc_and_in_order(self) -> None:
        early = datetime(2024, 1, 9, tzinfo=UTC)
        late = early + timedelta(days=1)

        assert BarHistory(SPY, (), fetched=(early, late)).fetched == (early, late)
        with pytest.raises(ValueError, match="oldest is after newest"):
            BarHistory(SPY, (), fetched=(late, early))
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            BarHistory(SPY, (), fetched=(early.replace(tzinfo=None), late))

    def test_is_immutable(self) -> None:
        history = BarHistory(SPY, (bar(DAYS[0]),))
        assert replace(history) == history

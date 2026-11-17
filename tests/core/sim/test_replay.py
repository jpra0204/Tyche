"""The historical replay: sessions in time order, bars at their close, nothing early."""

from datetime import UTC, date, datetime

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    AssetClass,
    BarHistory,
    Currency,
    DataIssue,
    DataIssueKind,
    Instrument,
    PriceAdjustment,
    Timeframe,
)
from tyche.core.events import BarEvent, DataQualityEvent, DataReadyEvent, SessionEvent, SessionPhase
from tyche.core.ports import Calendar
from tyche.core.sim import HistoricalReplay, cycle_id

XIU = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)


@pytest.fixture(scope="module")
def calendars() -> dict[str, Calendar]:
    return {
        mic: ExchangeCalendarsCalendar(mic, first=date(2023, 12, 1), last=date(2024, 3, 31))
        for mic in ("XNYS", "XTSE")
    }


def history(instrument: Instrument, days: list[date], *issues: DataIssue) -> BarHistory:
    return BarHistory(instrument, tuple(bar(day, instrument=instrument) for day in days), issues)


def describe(replay: HistoricalReplay) -> list[str]:
    out = []
    for item in replay.inputs():
        event = item.event
        if isinstance(event, SessionEvent):
            out.append(f"{event.phase} {event.session.calendar}")
        elif isinstance(event, BarEvent):
            out.append(f"bar {event.bar.instrument.symbol}")
        elif isinstance(event, DataQualityEvent):
            out.append(f"issue {event.issue.kind}")
        elif isinstance(event, DataReadyEvent):
            out.append("ready")
    return out


class TestOneSession:
    def test_inputs_come_in_a_fixed_order(self, calendars: dict[str, Calendar]) -> None:
        day = date(2024, 1, 2)
        replay = HistoricalReplay([history(SPY, [day]), history(QQQ, [day])], calendars, day, day)

        assert describe(replay) == ["open XNYS", "bar SPY", "bar QQQ", "close XNYS", "ready"]

    def test_each_input_happens_at_the_right_moment(self, calendars: dict[str, Calendar]) -> None:
        day = date(2024, 1, 2)
        replay = HistoricalReplay([history(SPY, [day])], calendars, day, day)

        moments = [item.at for item in replay.inputs()]

        assert moments == [datetime(2024, 1, 2, 14, 30, tzinfo=UTC)] + [close_of(day)] * 3
        assert replay.start == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)

    def test_a_bar_is_never_scheduled_before_its_own_timestamp(
        self, calendars: dict[str, Calendar]
    ) -> None:
        replay = HistoricalReplay(
            [history(SPY, JANUARY_2024)], calendars, JANUARY_2024[0], JANUARY_2024[-1]
        )

        bars = [
            (item.at, item.event.bar.timestamp)
            for item in replay.inputs()
            if isinstance(item.event, BarEvent)
        ]

        assert len(bars) == len(JANUARY_2024)
        assert all(at == stamp for at, stamp in bars)

    def test_data_ready_starts_a_cycle_and_lists_what_arrived(
        self, calendars: dict[str, Calendar]
    ) -> None:
        day = date(2024, 1, 2)
        replay = HistoricalReplay([history(SPY, [day]), history(QQQ, [])], calendars, day, day)

        [ready] = [item for item in replay.inputs() if isinstance(item.event, DataReadyEvent)]

        assert ready.cycle_id == "XNYS:2024-01-02:1d"
        assert isinstance(ready.event, DataReadyEvent)
        assert ready.event.timeframe is Timeframe.D1
        assert ready.event.as_of == close_of(day)
        assert ready.event.delivered == (SPY,)
        assert ready.event.missing == (QQQ,)
        assert "bar QQQ" not in describe(replay)


class TestRange:
    def test_replays_only_sessions_in_the_range(self, calendars: dict[str, Calendar]) -> None:
        replay = HistoricalReplay(
            [history(SPY, JANUARY_2024)], calendars, date(2024, 1, 4), date(2024, 1, 8)
        )

        days = [
            item.event.session.day
            for item in replay.inputs()
            if isinstance(item.event, SessionEvent) and item.event.phase is SessionPhase.OPEN
        ]

        assert days == [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]

    def test_a_range_with_no_sessions_has_no_inputs(self, calendars: dict[str, Calendar]) -> None:
        replay = HistoricalReplay(
            [history(SPY, [])], calendars, date(2024, 1, 13), date(2024, 1, 15)
        )

        assert list(replay.inputs()) == []
        assert replay.start is None


class TestIssues:
    def test_an_issue_is_replayed_at_its_sessions_close(
        self, calendars: dict[str, Calendar]
    ) -> None:
        missing = DataIssue(DataIssueKind.MISSING_SESSION, SPY, date(2024, 1, 3), "no bar")
        replay = HistoricalReplay(
            [history(SPY, [date(2024, 1, 2)], missing)],
            calendars,
            date(2024, 1, 2),
            date(2024, 1, 3),
        )

        assert describe(replay)[4:] == ["open XNYS", "issue missing_session", "close XNYS", "ready"]

    def test_an_issue_without_a_session_comes_first(self, calendars: dict[str, Calendar]) -> None:
        dropped = DataIssue(DataIssueKind.OFF_SESSION, SPY, None, "dropped a bar on a Saturday")
        replay = HistoricalReplay(
            [history(SPY, [date(2024, 1, 2)], dropped)],
            calendars,
            date(2024, 1, 2),
            date(2024, 1, 2),
        )

        assert describe(replay)[0] == "issue off_session"
        assert next(iter(replay.inputs())).at == replay.start


class TestTwoMarkets:
    def test_calendars_are_merged_in_time_order(self, calendars: dict[str, Calendar]) -> None:
        # 15 January 2024: Martin Luther King Jr. Day closes New York; Toronto is open.
        days = [date(2024, 1, 12), date(2024, 1, 15), date(2024, 1, 16)]
        replay = HistoricalReplay(
            [history(SPY, [d for d in days if d != date(2024, 1, 15)]), history(XIU, days)],
            calendars,
            days[0],
            days[-1],
        )

        cycles = [item.cycle_id for item in replay.inputs() if item.cycle_id]
        moments = [item.at for item in replay.inputs()]

        assert cycles == [
            "XNYS:2024-01-12:1d",
            "XTSE:2024-01-12:1d",
            "XTSE:2024-01-15:1d",
            "XNYS:2024-01-16:1d",
            "XTSE:2024-01-16:1d",
        ]
        assert moments == sorted(moments)


class TestValidation:
    def test_rejects_an_empty_range(self, calendars: dict[str, Calendar]) -> None:
        with pytest.raises(ValueError, match="empty replay range"):
            HistoricalReplay([], calendars, date(2024, 1, 5), date(2024, 1, 2))

    def test_rejects_an_instrument_twice(self, calendars: dict[str, Calendar]) -> None:
        with pytest.raises(ValueError, match="only one history"):
            HistoricalReplay(
                [history(SPY, []), history(SPY, [])], calendars, date(2024, 1, 2), date(2024, 1, 5)
            )

    def test_rejects_an_instrument_without_its_calendar(self) -> None:
        with pytest.raises(ValueError, match="no calendar loaded for XNYS"):
            HistoricalReplay([history(SPY, [])], {}, date(2024, 1, 2), date(2024, 1, 5))


def test_cycle_ids_name_the_calendar_and_the_day() -> None:
    from tests.support.market import session

    assert cycle_id(session(date(2024, 1, 2))) == "XNYS:2024-01-02:1d"


def test_adjustment_basis_is_untouched(calendars: dict[str, Calendar]) -> None:
    replay = HistoricalReplay(
        [history(SPY, [date(2024, 1, 2)])], calendars, date(2024, 1, 2), date(2024, 1, 2)
    )

    [bar_input] = [i for i in replay.inputs() if isinstance(i.event, BarEvent)]

    assert isinstance(bar_input.event, BarEvent)
    assert bar_input.event.bar.adjustment is PriceAdjustment.SPLITS

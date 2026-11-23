"""The backtest runner: the whole trading path, warmed up, kept out of the holdout.

Uses the real New York calendar and a data provider that makes a bar for every session,
so the dates are real and the prices are simple: SPY at 470 rising 0.10 a session,
QQQ at 400.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

import pytest

from tests.support.costs import US_COSTS, usd
from tests.support.market import QQQ, SPY, bar
from tests.support.profiles import US_PROFILE
from tests.support.risk import UNBOUND
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.backtest import (
    BacktestError,
    BacktestSettings,
    BacktestSpec,
    HoldoutError,
    run_backtest,
)
from tyche.core.domain import (
    BarHistory,
    Instrument,
    PriceAdjustment,
    Side,
    audit_daily_bars,
)
from tyche.core.events import RunEvent, RunMode
from tyche.core.ports import Calendar
from tyche.strategies.buy_and_hold import BuyAndHold

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 6, 1), last=date(2024, 3, 31))
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 31)
SETTINGS = BacktestSettings(holdout_starts=date(2024, 2, 1), starting_cash=usd("10000"))
START_PRICES = {SPY: 470.0, QQQ: 400.0}


@dataclass
class SyntheticData:
    """A ``DataProvider`` with a bar at every session close of ``calendar``."""

    calendar: Calendar = NYSE
    extra_sessions: int = 0
    """Sessions past ``last`` to add anyway, as a provider with a bug would."""
    calls: list[tuple[Instrument, date, date]] = field(default_factory=list)

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        self.calls.append((instrument, first, last))
        sessions = list(self.calendar.sessions_between(first, last))
        for _ in range(self.extra_sessions):
            sessions.append(self.calendar.next_session(sessions[-1].day))
        bars = [
            bar(
                s.day,
                START_PRICES[instrument] + (0.1 * i if instrument == SPY else 0.0),
                instrument=instrument,
                timestamp=s.closes_at,
            )
            for i, s in enumerate(sessions)
        ]
        if self.extra_sessions:
            return BarHistory(instrument, tuple(bars))
        return audit_daily_bars(instrument, bars, sessions, adjustment=PriceAdjustment.SPLITS)


def spec(**changes: object) -> BacktestSpec:
    base = BacktestSpec(
        run_id="bt-test",
        code_version="0.0.0+gtest",
        config_hash="sha256:test",
        profile=US_PROFILE,
        costs=US_COSTS,
        strategies=(BuyAndHold(SPY),),
        budgets={"buy_and_hold": Decimal(1)},
        risk=UNBOUND,
        settings=SETTINGS,
        first=FIRST,
        last=LAST,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def calendars(calendar: Calendar = NYSE) -> dict[str, Calendar]:
    return {"XNYS": calendar}


class TestTheHoldout:
    def test_a_range_reaching_the_holdout_is_refused_before_any_data_is_read(self) -> None:
        data = SyntheticData()

        with pytest.raises(HoldoutError, match="reserved holdout"):
            run_backtest(spec(last=date(2024, 2, 1)), data, calendars())

        assert data.calls == []

    def test_no_history_is_loaded_past_the_last_day(self) -> None:
        data = SyntheticData()

        run_backtest(spec(), data, calendars())

        assert {last for _, _, last in data.calls} == {LAST}

    def test_a_provider_returning_bars_past_the_range_is_refused(self) -> None:
        with pytest.raises(BacktestError, match="none of the holdout, can be seen"):
            run_backtest(spec(), SyntheticData(extra_sessions=1), calendars())


class TestWarmUp:
    def test_loads_the_sessions_the_stages_need_before_the_first_day(self) -> None:
        data = SyntheticData()

        result = run_backtest(spec(), data, calendars())

        # The universe's liquidity average needs 20 sessions; buy-and-hold needs 1.
        assert result.warm_up_needed == 20
        expected = NYSE.sessions_between(date(2023, 11, 1), date(2023, 12, 29))[-20:]
        assert result.warm_up["XNYS"] == expected
        assert {first for _, first, _ in data.calls} == {expected[0].day}
        assert [i for i, _, _ in data.calls] == [SPY, QQQ]

    def test_warmed_up_strategies_trade_from_the_first_decision(self) -> None:
        result = run_backtest(spec(), SyntheticData(), calendars())

        first_fill = result.fills[0]
        assert (first_fill.instrument, first_fill.side) == (SPY, Side.BUY)
        assert first_fill.trade_date == date(2024, 1, 3)  # decided at the close of 2 January

    def test_a_calendar_starting_too_late_gives_a_shorter_warm_up_not_an_error(self) -> None:
        late = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 20), last=date(2024, 3, 31))

        result = run_backtest(spec(), SyntheticData(calendar=late), calendars(late))

        assert len(result.warm_up["XNYS"]) < 20
        assert result.run.completed
        # Without 20 bars, SPY is not eligible at first, so the entry comes later.
        assert result.fills[0].trade_date > date(2024, 1, 3)


class TestTheRun:
    def test_completes_with_tyche_and_the_broker_agreeing(self) -> None:
        result = run_backtest(spec(), SyntheticData(), calendars())

        assert result.run.completed, result.run.failure
        assert result.account == result.broker_account
        assert result.free_riding == ()

    def test_records_the_account_at_every_session_close(self) -> None:
        result = run_backtest(spec(), SyntheticData(), calendars())

        sessions = NYSE.sessions_between(FIRST, LAST)
        assert result.sessions["XNYS"] == sessions
        assert [c.as_of for c in result.closes] == [s.closes_at for s in sessions]

    def test_buy_and_hold_ends_invested_in_its_instrument(self) -> None:
        result = run_backtest(spec(), SyntheticData(), calendars())

        position = result.account.position(SPY)
        assert position is not None
        assert position.quantity > 0
        assert [f.side for f in result.fills] == [Side.BUY]

    def test_announces_the_run_with_its_code_version_and_config_hash(self) -> None:
        result = run_backtest(spec(), SyntheticData(), calendars())

        started = result.journal.of_type(RunEvent)[0].event
        assert (started.run_id, started.mode) == ("bt-test", RunMode.BACKTEST)
        assert (started.code_version, started.config_hash) == ("0.0.0+gtest", "sha256:test")

    def test_the_same_inputs_give_the_same_run(self) -> None:
        def fingerprint() -> Sequence[object]:
            result = run_backtest(spec(), SyntheticData(), calendars())
            return [(f.trade_date, f.quantity, f.price) for f in result.fills] + [
                c.account.equity(SPY.currency) for c in result.closes
            ]

        assert fingerprint() == fingerprint()


class TestRefusedSetups:
    def test_a_range_without_a_session(self) -> None:
        new_year = date(2024, 1, 1)

        with pytest.raises(BacktestError, match="no XNYS session between 2024-01-01"):
            run_backtest(spec(first=new_year, last=new_year), SyntheticData(), calendars())

    def test_an_empty_range(self) -> None:
        with pytest.raises(BacktestError, match="empty range"):
            run_backtest(spec(first=LAST, last=FIRST), SyntheticData(), calendars())

    def test_a_profile_without_instruments(self) -> None:
        profile = replace(US_PROFILE, universe=replace(US_PROFILE.universe, instruments=()))

        with pytest.raises(BacktestError, match="lists no instruments"):
            run_backtest(spec(profile=profile), SyntheticData(), calendars())

    def test_a_missing_calendar(self) -> None:
        with pytest.raises(BacktestError, match="no calendar loaded for XNYS"):
            run_backtest(spec(), SyntheticData(), {})


class TestTheBenchmark:
    def test_a_benchmark_that_is_a_candidate_is_loaded_once(self) -> None:
        data = SyntheticData()

        result = run_backtest(spec(), data, calendars())

        assert result.benchmark.instrument == SPY
        assert [instrument for instrument, _, _ in data.calls].count(SPY) == 1
        assert result.benchmark in result.histories

    def test_a_benchmark_that_is_not_a_candidate_is_loaded_over_the_same_days(self) -> None:
        profile = replace(
            US_PROFILE,
            universe=replace(US_PROFILE.universe, instruments=(SPY,)),
            benchmark=QQQ,
        )
        data = SyntheticData()

        result = run_backtest(spec(profile=profile), data, calendars())

        assert result.benchmark.instrument == QQQ
        assert result.benchmark not in result.histories
        (_, spy_first, spy_last), (_, qqq_first, qqq_last) = data.calls
        assert (qqq_first, qqq_last) == (spy_first, spy_last)

    def test_a_benchmark_without_a_bar_to_start_from_is_refused(self) -> None:
        @dataclass
        class NoBenchmarkData(SyntheticData):
            def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
                if instrument == QQQ:
                    return BarHistory(QQQ, ())
                return super().daily_bars(instrument, first, last)

        profile = replace(
            US_PROFILE,
            universe=replace(US_PROFILE.universe, instruments=(SPY,)),
            benchmark=QQQ,
        )

        with pytest.raises(BacktestError, match="no bar of the benchmark QQQ@XNAS on or before"):
            run_backtest(spec(profile=profile), NoBenchmarkData(), calendars())

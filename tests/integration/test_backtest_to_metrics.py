"""From a backtest to its metrics, checked against a golden file (Phase 1, PR 16).

A fixed run on the real New York calendar, second half of 2023, with made-up prices:

* SPY and QQQ move in waves around a slow rise, so there are drawdowns and recoveries.
* SPY pays a dividend each quarter, which the benchmark reinvests and the account
  receives as cash.
* Two sleeves: buy-and-hold QQQ with half the account, and a strategy that holds SPY
  for two weeks out of four with the other half, so trades open and close.

The whole result goes through ``metrics.json``'s serialiser and is compared with
``golden/backtest_metrics.json``. Any change to the trading path, the cost model or a
metric's definition changes a number and fails this test. If the change is intended,
regenerate the file and review the diff number by number in the pull request::

    TYCHE_UPDATE_GOLDEN=1 uv run pytest tests/integration/test_backtest_to_metrics.py
"""

import json
import math
import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from tests.support.costs import US_COSTS, usd
from tests.support.market import QQQ, SPY, bar, dividend
from tests.support.profiles import US_PROFILE
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.backtest import BacktestSettings, BacktestSpec, measure_backtest, run_backtest
from tyche.core.domain import (
    BarHistory,
    Currency,
    Instrument,
    PriceAdjustment,
    Target,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.pipeline.signals import StrategyContext
from tyche.runtime.backtest import metrics_record
from tyche.strategies.buy_and_hold import BuyAndHold

SHAPES = {SPY: (440.0, 0.06, 9.0), QQQ: (370.0, 0.09, 6.0)}
"""Per instrument: the first price, the waves' amplitude, and their period in sessions."""

GOLDEN = Path(__file__).parent / "golden" / "backtest_metrics.json"
NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 1, 1), last=date(2024, 3, 31))
FIRST, LAST = date(2023, 7, 3), date(2023, 12, 29)
DIVIDENDS = {date(2023, 9, 15): "1.58", date(2023, 12, 15): "1.91"}


class WavyData:
    """A ``DataProvider`` with a bar at every session: a slow rise with waves."""

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        start, amplitude, period = SHAPES[instrument]
        sessions = NYSE.sessions_between(first, last)
        bars = [
            bar(
                s.day,
                round(start * (1 + 0.0004 * i + amplitude * math.sin(i / period)), 2),
                instrument=instrument,
                timestamp=s.closes_at,
            )
            for i, s in enumerate(sessions)
        ]
        history = audit_daily_bars(instrument, bars, sessions, adjustment=PriceAdjustment.SPLITS)
        if instrument != SPY:
            return history
        paid = tuple(
            dividend(day, amount) for day, amount in DIVIDENDS.items() if first <= day <= last
        )
        return BarHistory(SPY, history.bars, history.issues, distributions=paid)


class TwoWeeksInTwoWeeksOut:
    """Holds SPY in even fortnights, nothing in odd ones."""

    strategy_id = "fortnights"
    version = "1"
    timeframe = Timeframe.D1
    lookback = 1

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        if SPY not in context.instruments:
            return ()
        holding = (context.as_of.date().toordinal() // 14) % 2 == 0
        weight = Decimal(1) if holding else Decimal(0)
        return (Target(SPY, weight, "in" if holding else "out"),)


def run_metrics() -> dict[str, object]:
    spec = BacktestSpec(
        run_id="golden",
        code_version="0.0.0+ggolden",
        config_hash="sha256:golden",
        profile=US_PROFILE,
        costs=US_COSTS,
        strategies=(BuyAndHold(QQQ), TwoWeeksInTwoWeeksOut()),
        budgets={"buy_and_hold": Decimal("0.5"), "fortnights": Decimal("0.5")},
        settings=BacktestSettings(holdout_starts=date(2024, 1, 1), starting_cash=usd("10000")),
        first=FIRST,
        last=LAST,
    )
    result = run_backtest(spec, WavyData(), {"XNYS": NYSE})
    assert result.run.completed, result.run.failure
    assert result.account == result.broker_account
    return metrics_record("golden", measure_backtest(result, Currency.USD))


def test_the_metrics_match_the_golden_file() -> None:
    actual = run_metrics()
    if os.environ.get("TYCHE_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert actual == expected


def test_the_run_exercises_every_metric() -> None:
    """Guards the golden file's usefulness: every figure is a number, none is missing."""
    metrics = run_metrics()
    strategy, benchmark, trading = metrics["strategy"], metrics["benchmark"], metrics["trading"]
    assert isinstance(strategy, dict)
    assert isinstance(benchmark, dict)
    assert isinstance(trading, dict)

    assert all(value is not None for value in strategy.values())
    assert strategy["max_drawdown"]["recovered"] is None
    assert benchmark["max_drawdown"]["recovered"] is not None
    assert trading["closed_trades"] > 2
    assert 0 < Decimal(trading["win_rate"]) < 1
    assert trading["still_open"] >= 1

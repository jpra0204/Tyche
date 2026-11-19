"""Tyche against backtesting.py on made-up prices (Phase 1, PR 17, ADR-0026).

Three years of the real New York calendar, 2021 to 2023, with a seeded random walk:
small gaps at the open, enough swings around a 20-session average to trade dozens of
times. Two account sizes, so that both sides of IBKR's commission are used: at
USD 10,000 the USD 1.00 minimum binds, at USD 1,000,000 the per-share rate does.

How the two engines are lined up, and what they cannot share, is in
``tests/reference/comparison.py``.
"""

import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.reference.comparison import (
    Runs,
    assert_same_equity,
    assert_same_fills,
    assert_same_metrics,
    assert_same_trades,
    run_both,
)
from tests.support.market import SPY
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data.yfinance_source import YFinanceSource, yfinance_fetcher
from tyche.core.domain import (
    Bar,
    BarHistory,
    Instrument,
    PriceAdjustment,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.ports import Calendar

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2020, 1, 2), last=date(2024, 3, 28))
FIRST, LAST = date(2021, 1, 4), date(2023, 12, 29)
SESSIONS = 20
SEED = 17


class RandomWalk:
    """A ``DataProvider`` with one bar per session: a seeded random walk from USD 100.

    The walk is drawn once from the calendar's first session, so every range asked for
    sees the same prices.
    """

    def __init__(self) -> None:
        draw = random.Random(SEED)
        self._bars: list[Bar] = []
        close = 100.0
        for session in NYSE.sessions_between(date(2020, 1, 2), LAST):
            open_ = round(close * (1 + draw.gauss(0, 0.004)), 2)
            close = round(open_ * (1 + draw.gauss(0.0003, 0.012)), 2)
            high = round(max(open_, close) * (1 + abs(draw.gauss(0, 0.004))), 2)
            low = round(min(open_, close) * (1 - abs(draw.gauss(0, 0.004))), 2)
            self._bars.append(
                Bar(
                    instrument=SPY,
                    timeframe=Timeframe.D1,
                    timestamp=session.closes_at,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=5_000_000.0,
                    adjustment=PriceAdjustment.SPLITS,
                )
            )

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        assert instrument == SPY
        sessions = NYSE.sessions_between(first, last)
        days = {session.day for session in sessions}
        bars = [bar for bar in self._bars if bar.timestamp.date() in days]
        return audit_daily_bars(SPY, bars, sessions, adjustment=PriceAdjustment.SPLITS)


@pytest.fixture(scope="module", params=["10000", "1000000"], ids=["minimum", "per-share"])
def runs(request: pytest.FixtureRequest) -> Runs:
    return run_both(SPY, SESSIONS, RandomWalk(), NYSE, FIRST, LAST, Decimal(request.param))


def test_the_run_trades_enough_to_compare(runs: Runs) -> None:
    """Guards the comparison's usefulness: many round trips, winners and losers."""
    trades = runs.metrics.trades.closed
    assert len(trades) >= 20
    assert any(trade.profit.amount > 0 for trade in trades)
    assert any(trade.profit.amount < 0 for trade in trades)


def test_the_same_fills(runs: Runs) -> None:
    assert_same_fills(runs)


def test_the_same_equity_at_every_close(runs: Runs) -> None:
    assert_same_equity(runs)


def test_the_same_trades(runs: Runs) -> None:
    assert_same_trades(runs)


def test_the_same_metrics(runs: Runs) -> None:
    assert_same_metrics(runs)


class YahooWithoutDividends:
    """A ``DataProvider`` over SPY's real daily bars from Yahoo, with its dividends removed.

    backtesting.py has no dividends, so the comparison leaves them out on both sides.
    SPY has had no split, so its bars are as Yahoo sends them.
    """

    def __init__(self, calendar: Calendar, cache_dir: Path, first: date, last: date) -> None:
        source = YFinanceSource({calendar.mic: calendar}, fetch=yfinance_fetcher(cache_dir))
        fetched = source.fetch_daily(SPY, first, last)
        assert not fetched.splits
        self._calendar = calendar
        self._bars = fetched.bars

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        assert instrument == SPY
        sessions = self._calendar.sessions_between(first, last)
        days = {session.day for session in sessions}
        bars = [bar for bar in self._bars if bar.timestamp.date() in days]
        return audit_daily_bars(SPY, bars, sessions, adjustment=PriceAdjustment.SPLITS)


@pytest.mark.network
def test_real_spy_from_2005_to_2023(tmp_path: Path) -> None:
    """Opt-in: ``uv run pytest -m network``. The same comparison on 19 years of real SPY bars.

    A 50-session average, USD 10,000. Real data brings what made-up prices do not: gaps
    at the open of up to 10% (October 2008, March 2020) and 4,781 sessions of compounding.
    """
    nyse = ExchangeCalendarsCalendar("XNYS", first=date(2004, 1, 2), last=date(2024, 3, 28))
    data = YahooWithoutDividends(nyse, tmp_path, date(2004, 6, 1), date(2023, 12, 29))

    real = run_both(SPY, 50, data, nyse, date(2005, 1, 3), date(2023, 12, 29), Decimal(10_000))

    assert len(real.metrics.trades.closed) >= 50
    assert_same_fills(real)
    assert_same_equity(real)
    assert_same_trades(real)
    assert_same_metrics(real)

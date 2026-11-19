"""Tyche and backtesting.py, run on the same bars and compared (Phase 1, PR 17, ADR-0026).

backtesting.py is an independent backtester: other authors, other code, ``float``
arithmetic instead of ``Decimal``. Running one strategy through both and finding the
same fills, the same equity at every close and the same trades says Tyche's
simulator and ledger do their sums right. A disagreement is a bug in one of them.

**What is compared.** Fill days, share counts and prices; the cash of every closed
trade; equity at every session close from the first trading day; and the metrics
whose definitions both share (total return, maximum drawdown, win rate). The other
metrics (CAGR, volatility, Sharpe, Sortino) are computed again with pandas from
backtesting.py's equity curve, using Tyche's written conventions, which checks
Tyche's ``Decimal`` arithmetic against numpy's.

**How the two are made to agree.** The comparison runs Tyche as the ``US`` profile
configures it, with one change: no regulatory fees. Everything else is mapped onto
backtesting.py:

* *Next-open fills.* Both decide at a close and fill market orders at the next open.
* *Whole shares.* Both strategies size an entry as ``floor(0.95 * equity / close)``.
  At 95%, Tyche's 2% price buffer never shrinks a purchase, and its 10% rebalance
  band never resizes a holding, so every Tyche order is an entry or a full exit, as
  every backtesting.py order is.
* *Commission.* ``ibkr_pro_fixed`` writes IBKR Pro Fixed again from the published
  schedule, independently of ``tyche.core.domain.costs``.
* *Slippage.* backtesting.py's ``spread`` moves only the entry price, not the exit,
  so it cannot model Tyche's slippage on both sides. The comparison charges it as
  commission instead: ``shares * price * slippage`` on every fill. The cash is the
  same; the recorded prices differ by the slippage, and the comparison checks that.

**What is left out, because backtesting.py does not model it:** regulatory fees (its
commission function is not told whether an order buys or sells, and the SEC fee is
on sales only), dividends (the bars carry none here), T+1 settlement (a strategy that
is never more than 95% invested never waits for cash), the volume cap (it never
binds at these sizes) and stops (it fills a stop on the bar its entry filled, Tyche
from the next session, ADR-0023).
"""

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, ClassVar

import pandas as pd
from backtesting import Backtest
from backtesting import Strategy as ReferenceStrategy

from tests.support.costs import NO_FEES, US_COSTS
from tests.support.profiles import US_PROFILE
from tyche.core.backtest import (
    BacktestMetrics,
    BacktestResult,
    BacktestSettings,
    BacktestSpec,
    measure_backtest,
    run_backtest,
)
from tyche.core.domain import Currency, Instrument, Money, Side, Target, Timeframe
from tyche.core.pipeline.signals import StrategyContext
from tyche.core.ports import Calendar, DataProvider

WEIGHT = Decimal("0.95")
"""The fraction of equity an entry buys, in both engines."""

SESSIONS_PER_YEAR = 252
SECONDS_PER_YEAR = 365.25 * 86_400

COSTS = replace(US_COSTS, regulatory_fees=NO_FEES)
"""Tyche's ``US`` costs without regulatory fees, which backtesting.py cannot model."""

SLIPPAGE = float(COSTS.slippage_bps) / 10_000

MONEY_TOLERANCE = 1e-6
"""Largest difference allowed in an amount of money, in dollars: a ten-thousandth of a cent.

The two engines do the same sums, one in ``Decimal`` and one in ``float``; what is left
is ``float`` rounding, many orders of magnitude below this.
"""

RATIO_TOLERANCE = 1e-9
"""Largest difference allowed in a ratio, such as a return or a Sharpe ratio."""


def ibkr_pro_fixed(size: float, price: float) -> float:
    """IBKR Pro Fixed for US stocks, plus slippage, as backtesting.py's commission function.

    Written from IBKR's published schedule, as recorded in the cost summary (checked
    2026-11-17): USD 0.005 a share, at least USD 1.00, at most 1% of the trade's value,
    rounded to the cent. The cap uses the price before slippage; it never binds at
    these prices. ``Decimal`` keeps half-cent amounts rounding the way Tyche's do.

    backtesting.py calls it with a positive size for an entry and for its exit alike,
    so it cannot tell a purchase from a sale. Slippage costs the same on both sides,
    which is why it can be charged here.
    """
    shares = Decimal(abs(int(size)))
    by_shares = max(Decimal("0.005") * shares, Decimal("1.00"))
    cap = Decimal(repr(float(price))) * shares * Decimal("0.01")
    commission = min(by_shares, cap).quantize(Decimal("0.01"), ROUND_HALF_EVEN)
    return float(commission) + abs(size) * price * SLIPPAGE


class AboveItsAverage:
    """Tyche's side: holds the instrument while its close is above its recent average.

    Wants ``WEIGHT`` of equity in the instrument when the last close is above the mean
    of the last ``sessions`` closes, nothing otherwise.
    """

    strategy_id = "above_average"
    version = "1"
    timeframe = Timeframe.D1

    def __init__(self, instrument: Instrument, sessions: int) -> None:
        self.instrument = instrument
        self.lookback = sessions

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        if self.instrument not in context.instruments:
            return ()
        closes = [bar.close for bar in context.history.bars(self.instrument, Timeframe.D1)]
        if closes[-1] > sum(closes) / len(closes):
            return (Target(self.instrument, WEIGHT, "above its average"),)
        return (Target(self.instrument, Decimal(0), "at or below its average"),)


class ReferenceAboveItsAverage(ReferenceStrategy):  # type: ignore[misc]
    """backtesting.py's side: the same rule, written against its own API.

    It decides nothing before ``first``, the day Tyche's run starts; the bars before it
    are the warm-up Tyche loaded.
    """

    sessions: ClassVar[int] = 0
    first: ClassVar[pd.Timestamp] = pd.Timestamp(0)
    weight: ClassVar[float] = float(WEIGHT)

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self.data.index[-1] < self.first:
            return
        closes = [float(close) for close in self.data.Close[-self.sessions :]]
        above = closes[-1] > sum(closes) / len(closes)
        if above and not self.position:
            self.buy(size=int(self.weight * self.equity // closes[-1]))
        elif not above and self.position:
            self.position.close()


@dataclass(frozen=True)
class Runs:
    """One strategy run through both engines."""

    tyche: BacktestResult
    metrics: BacktestMetrics
    stats: Any
    """backtesting.py's statistics: a ``pandas.Series`` with ``_equity_curve`` and ``_trades``."""


def run_both(
    instrument: Instrument,
    sessions: int,
    data: DataProvider,
    calendar: Calendar,
    first: date,
    last: date,
    starting_cash: Decimal,
) -> Runs:
    """Run ``AboveItsAverage`` in Tyche, then the same rule in backtesting.py on Tyche's bars."""
    profile = replace(
        US_PROFILE,
        universe=replace(US_PROFILE.universe, instruments=(instrument,)),
        benchmark=instrument,
    )
    spec = BacktestSpec(
        run_id="reference",
        code_version="0.0.0+greference",
        config_hash=None,
        profile=profile,
        costs=COSTS,
        strategies=(AboveItsAverage(instrument, sessions),),
        budgets={AboveItsAverage.strategy_id: Decimal(1)},
        settings=BacktestSettings(
            holdout_starts=date(2024, 1, 1),
            starting_cash=Money(starting_cash, Currency.USD),
        ),
        first=first,
        last=last,
    )
    result = run_backtest(spec, data, {calendar.mic: calendar})
    assert result.run.completed, result.run.failure
    assert result.account == result.broker_account

    (history,) = result.histories
    frame = pd.DataFrame(
        {
            "Open": [bar.open for bar in history.bars],
            "High": [bar.high for bar in history.bars],
            "Low": [bar.low for bar in history.bars],
            "Close": [bar.close for bar in history.bars],
            "Volume": [bar.volume for bar in history.bars],
        },
        index=pd.DatetimeIndex([_naive(bar.timestamp) for bar in history.bars]),
    )
    first_close = result.sessions[calendar.mic][0].closes_at
    strategy = type(
        "Reference",
        (ReferenceAboveItsAverage,),
        {"sessions": sessions, "first": pd.Timestamp(_naive(first_close))},
    )
    backtest = Backtest(frame, strategy, cash=float(starting_cash), commission=ibkr_pro_fixed)
    with warnings.catch_warnings():
        # backtesting.py warns when a position is still open at the end. Tyche's metrics
        # count such a position without judging it, and so does this comparison.
        warnings.filterwarnings("ignore", message="Some trades remain open", category=UserWarning)
        stats = backtest.run()
    return Runs(result, measure_backtest(result, Currency.USD), stats)


def _naive(moment: datetime) -> datetime:
    """A UTC moment without its time zone, as backtesting.py's index wants it."""
    return moment.replace(tzinfo=None)


def assert_same_fills(runs: Runs) -> None:
    """Each Tyche fill is a backtesting.py entry or exit: same day, side, shares and price.

    backtesting.py's prices are before slippage (it is charged as commission), so
    Tyche's must be theirs moved against the order by the slippage.
    """
    expected: list[tuple[date, Side, int, float]] = []
    for row in runs.stats._trades.itertuples():
        expected.append((row.EntryTime.date(), Side.BUY, int(row.Size), row.EntryPrice))
        expected.append((row.ExitTime.date(), Side.SELL, int(row.Size), row.ExitPrice))
    for trade in runs.stats._strategy.trades:  # still open at the end
        expected.append((trade.entry_time.date(), Side.BUY, int(trade.size), trade.entry_price))
    # Within a day, sales before purchases, as Tyche orders them.
    expected.sort(key=lambda fill: (fill[0], fill[1] is Side.BUY))

    actual = sorted(runs.tyche.fills, key=lambda fill: (fill.trade_date, fill.side is Side.BUY))
    assert [(f.trade_date, f.side, int(f.quantity)) for f in actual] == [
        (day, side, size) for day, side, size, _ in expected
    ]
    for fill, (_, side, _, price) in zip(actual, expected, strict=True):
        slipped = price * (1 + SLIPPAGE) if side is Side.BUY else price * (1 - SLIPPAGE)
        assert math.isclose(float(fill.price.amount), slipped, abs_tol=MONEY_TOLERANCE), fill


def assert_same_equity(runs: Runs) -> None:
    """Equity at every session close of Tyche's run matches backtesting.py's."""
    curve = runs.stats._equity_curve["Equity"]
    points = runs.metrics.strategy
    tyche = {_naive(close.as_of): close.account.equity(Currency.USD) for close in runs.tyche.closes}
    assert len(tyche) == points.sessions
    worst = max(abs(float(equity.amount) - float(curve[at])) for at, equity in tyche.items())
    assert worst <= MONEY_TOLERANCE, f"equity differs by up to {worst} USD"


def assert_same_trades(runs: Runs) -> None:
    """The same closed trades, opened and closed on the same days, with the same profit."""
    trades = runs.stats._trades
    tyche = runs.metrics.trades
    assert len(tyche.closed) == len(trades)
    assert tyche.still_open == len(runs.stats._strategy.trades)
    for closed, row in zip(tyche.closed, trades.itertuples(), strict=True):
        assert (closed.opened, closed.closed) == (row.EntryTime.date(), row.ExitTime.date())
        assert math.isclose(float(closed.profit.amount), row.PnL, abs_tol=MONEY_TOLERANCE)
    wins = sum(1 for closed in tyche.closed if closed.profit.amount > 0)
    assert wins / len(tyche.closed) == runs.stats["Win Rate [%]"] / 100


def assert_same_metrics(runs: Runs) -> None:
    """Tyche's metrics against backtesting.py's, and against pandas on its equity curve."""
    tyche = runs.metrics.strategy
    curve = runs.stats._equity_curve["Equity"]
    curve = curve[curve.index >= _naive(tyche.first)]
    returns = curve.pct_change().dropna()
    years = (curve.index[-1] - curve.index[0]).total_seconds() / SECONDS_PER_YEAR
    downside = math.sqrt((returns.clip(upper=0) ** 2).mean())
    scale = math.sqrt(SESSIONS_PER_YEAR)
    assert tyche.max_drawdown is not None

    pairs = {
        # backtesting.py's own figures, where its definition is Tyche's.
        "total return": (tyche.total_return, runs.stats["Return [%]"] / 100),
        "max drawdown": (tyche.max_drawdown.depth, -runs.stats["Max. Drawdown [%]"] / 100),
        # Tyche's conventions, computed again with pandas.
        "cagr": (tyche.cagr, (curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1),
        "volatility": (tyche.volatility, returns.std(ddof=1) * scale),
        "sharpe": (tyche.sharpe, returns.mean() / returns.std(ddof=1) * scale),
        "sortino": (tyche.sortino, returns.mean() / downside * scale),
    }
    for name, (ours, theirs) in pairs.items():
        assert ours is not None, name
        assert math.isclose(float(ours), float(theirs), abs_tol=RATIO_TOLERANCE), (
            f"{name}: Tyche {ours}, reference {theirs}"
        )

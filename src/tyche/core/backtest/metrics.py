"""Performance metrics: how a backtest did, and how its benchmark did over the same days.

The benchmark is the market profile's index ETF held with every distribution
reinvested at the ex-date close, with no costs and no cash: the total return of simply
holding it (ADR-0025). It is a harder bar than Tyche's own buy-and-hold strategy, which
pays commissions and keeps distributions as cash until the rebalance band tops the
position up, and it is the right one: it is what holding the ETF pays.

Both series are measured the same way, from the same starting equity on the same
session closes. The definitions, chosen once so every report means the same thing:

* **Daily return**: equity at one session close over the previous close, minus one.
  A backtest has no deposits or withdrawals after the start, so no flow adjustment is
  needed.
* **Years**: calendar time from the first close to the last, in days of 365.25.
* **Total return**: last equity over first, minus one.
* **CAGR**: ``(1 + total return) ** (1 / years) - 1``.
* **Volatility**: sample standard deviation of the daily returns, times
  ``sqrt(252)``.
* **Sharpe ratio**: mean daily return over its standard deviation, times
  ``sqrt(252)``. The risk-free rate is zero, matching the simulator, where cash earns
  nothing (ADR-0025).
* **Sortino ratio**: mean daily return over the downside deviation, times
  ``sqrt(252)``. The downside deviation is the root mean square of the daily returns
  below zero, counting every day (the days above zero as zero).
* **Maximum drawdown**: the largest fall from a peak close to a later close, as a
  fraction of the peak, with when it peaked, bottomed and recovered.
* **Exposure**: the average, over every close, of the fraction of equity invested.
* **Turnover**: the value of every fill, bought and sold, over the average equity,
  per year. Buy-and-hold on SPY from 2005 to 2023 shows 0.03 a year.
* **Closed trades and win rate**: a trade runs from the fill that opens a position in
  an instrument to the fill that brings it back to zero, across all sleeves (fills are
  per account). Its profit is the cash of all its fills, commissions included;
  distributions received while it was open are not counted. The win rate is the
  fraction of closed trades with a profit above zero. Positions still open at the end
  are counted, not judged.

Ratios that cannot be computed (a volatility from fewer than two returns, a Sharpe
ratio with no variation) are ``None``, never zero or infinity.

Arithmetic is ``Decimal`` in a fixed context, so the same inputs give the same digits
on every machine and the golden-file test can compare them exactly.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise

from tyche.core.backtest.runner import BacktestResult
from tyche.core.domain import (
    Bar,
    BarHistory,
    Currency,
    Fill,
    Instrument,
    Money,
    Side,
)
from tyche.core.domain.validation import require_utc

SESSIONS_PER_YEAR = 252
"""Trading sessions in a year, by convention, for annualising daily figures."""

DAYS_PER_YEAR = Decimal("365.25")
"""Calendar days in a year, for the length of a run in years."""

RISK_FREE_RATE = Decimal(0)
"""The rate Sharpe and Sortino are measured over. Zero, as cash earns nothing in the
simulator; a real rate comes with interest on cash (ADR-0025)."""

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_SECONDS_PER_YEAR = DAYS_PER_YEAR * 86_400


class MetricsError(ValueError):
    """The inputs cannot be measured, for example a benchmark with no price to start from."""


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """Equity at one session close.

    Attributes:
        at: The close, in UTC.
        equity: Cash plus holdings at the close. Must be positive.
        invested: The holdings' value at the close, from zero to ``equity``.
    """

    at: datetime
    equity: Decimal
    invested: Decimal

    def __post_init__(self) -> None:
        require_utc(self.at, "EquityPoint at")
        if not self.equity.is_finite() or self.equity <= 0:
            raise MetricsError(f"equity at {self.at.isoformat()} must be positive")
        if not self.invested.is_finite() or self.invested < 0:
            raise MetricsError(f"invested at {self.at.isoformat()} cannot be negative")


@dataclass(frozen=True, slots=True)
class Drawdown:
    """A fall from a peak close to a later, lower close.

    Attributes:
        depth: The fraction of the peak lost at the bottom, above zero.
        peak: The close of the peak.
        trough: The close of the bottom.
        recovered: The first close back at or above the peak, or ``None`` if the
            series ended below it.
    """

    depth: Decimal
    peak: datetime
    trough: datetime
    recovered: datetime | None


@dataclass(frozen=True, slots=True)
class SeriesMetrics:
    """How one equity series did. Definitions in the module docstring."""

    first: datetime
    last: datetime
    sessions: int
    years: Decimal
    start_equity: Decimal
    end_equity: Decimal
    total_return: Decimal
    cagr: Decimal | None
    volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    max_drawdown: Drawdown | None
    exposure: Decimal


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """A position from the fill that opened it to the fill that closed it.

    Attributes:
        instrument: What was traded.
        opened: Trade date of the opening fill.
        closed: Trade date of the closing fill.
        profit: The cash of all its fills, commissions included. Distributions are not
            included.
    """

    instrument: Instrument
    opened: date
    closed: date
    profit: Money


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Closed trades, and how many positions were still open at the end."""

    closed: tuple[ClosedTrade, ...]
    still_open: int

    @property
    def wins(self) -> int:
        return sum(1 for trade in self.closed if trade.profit.is_positive)

    @property
    def win_rate(self) -> Decimal | None:
        """Fraction of closed trades with a profit, or ``None`` with no closed trade."""
        if not self.closed:
            return None
        with localcontext(_CONTEXT):
            return Decimal(self.wins) / Decimal(len(self.closed))


@dataclass(frozen=True, slots=True)
class Comparison:
    """The strategy's figures minus the benchmark's. ``None`` where either is ``None``.

    For the drawdown, a negative difference means the strategy fell less deeply.
    """

    total_return: Decimal
    cagr: Decimal | None
    volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    max_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Everything measured about a run, beside its benchmark.

    Attributes:
        currency: The currency equity is counted in.
        benchmark_instrument: The ETF the benchmark holds.
        strategy: The run's own equity, every strategy together.
        benchmark: The benchmark's total return from the same equity on the same closes.
        benchmark_equity: The benchmark's equity at each of the run's closes.
        versus_benchmark: Strategy minus benchmark.
        turnover: Value traded per year over the average equity; ``None`` for a run
            shorter than a session.
        traded: The value of every fill, bought and sold, before costs.
        costs: Every commission and regulatory fee paid.
        trades: Closed trades and positions left open.
    """

    currency: Currency
    benchmark_instrument: Instrument
    strategy: SeriesMetrics
    benchmark: SeriesMetrics
    benchmark_equity: tuple[EquityPoint, ...]
    versus_benchmark: Comparison
    turnover: Decimal | None
    traded: Money
    costs: Money
    trades: TradeStats


# --- one series ----------------------------------------------------------------------


def series_metrics(points: Sequence[EquityPoint]) -> SeriesMetrics:
    """Measure one equity series, given at every session close, oldest first."""
    if not points:
        raise MetricsError("no equity to measure")
    for previous, point in pairwise(points):
        if point.at <= previous.at:
            raise MetricsError("equity points must be in strictly increasing time order")
    with localcontext(_CONTEXT):
        first, last = points[0], points[-1]
        elapsed = last.at - first.at
        years = Decimal(elapsed.days * 86_400 + elapsed.seconds) / _SECONDS_PER_YEAR
        returns = [b.equity / a.equity - 1 for a, b in pairwise(points)]
        growth = last.equity / first.equity
        volatility = _stdev(returns)
        return SeriesMetrics(
            first=first.at,
            last=last.at,
            sessions=len(points),
            years=years,
            start_equity=first.equity,
            end_equity=last.equity,
            total_return=growth - 1,
            cagr=growth ** (1 / years) - 1 if years > 0 else None,
            volatility=volatility * _ANNUAL if volatility is not None else None,
            sharpe=_ratio(returns, volatility),
            sortino=_ratio(returns, _downside_deviation(returns)),
            max_drawdown=max_drawdown(points),
            exposure=sum((p.invested / p.equity for p in points), Decimal(0)) / len(points),
        )


_ANNUAL = Decimal(SESSIONS_PER_YEAR).sqrt(_CONTEXT)


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _stdev(returns: Sequence[Decimal]) -> Decimal | None:
    """Sample standard deviation, or ``None`` with fewer than two values."""
    if len(returns) < 2:
        return None
    mean = _mean(returns)
    variance = sum(((r - mean) ** 2 for r in returns), Decimal(0)) / (len(returns) - 1)
    return variance.sqrt()


def _downside_deviation(returns: Sequence[Decimal]) -> Decimal | None:
    """Root mean square of the returns below zero, over every day; ``None`` with none."""
    if not returns:
        return None
    below = sum((min(r, Decimal(0)) ** 2 for r in returns), Decimal(0))
    return (below / len(returns)).sqrt()


def _ratio(returns: Sequence[Decimal], spread: Decimal | None) -> Decimal | None:
    """Annualised mean excess return over ``spread``; ``None`` if it cannot be computed."""
    if not returns or spread is None or spread == 0:
        return None
    daily_risk_free = RISK_FREE_RATE / SESSIONS_PER_YEAR
    return (_mean(returns) - daily_risk_free) / spread * _ANNUAL


def max_drawdown(points: Sequence[EquityPoint]) -> Drawdown | None:
    """The deepest fall from a peak close to a later close, or ``None`` if it never fell."""
    with localcontext(_CONTEXT):
        peak = points[0]
        worst: tuple[Decimal, EquityPoint, EquityPoint] | None = None
        for point in points:
            if point.equity > peak.equity:
                peak = point
            depth = 1 - point.equity / peak.equity
            if depth > 0 and (worst is None or depth > worst[0]):
                worst = (depth, peak, point)
        if worst is None:
            return None
        depth, top, bottom = worst
        recovered = next(
            (p.at for p in points if p.at > bottom.at and p.equity >= top.equity), None
        )
        return Drawdown(depth, top.at, bottom.at, recovered)


# --- the benchmark -------------------------------------------------------------------


def benchmark_points(
    history: BarHistory, closes: Sequence[datetime], starting: Decimal
) -> tuple[EquityPoint, ...]:
    """The benchmark's equity at each of ``closes``, starting from ``starting``.

    At the first close, ``starting`` buys the benchmark at its latest close at or
    before it, whole and fractional units, with no cost. Each distribution with an
    ex-date after that bar is paid to the units held and reinvested at the close of
    the first bar on or after its ex-date. At every close the units are valued at the
    latest bar at or before it, so a session missing from the data repeats the
    previous value rather than inventing a price.

    Raises:
        MetricsError: No bar at or before the first close.
    """
    if not closes:
        return ()
    bars = history.bars
    start = _last_at_or_before(bars, closes[0])
    if start is None:
        raise MetricsError(
            f"no bar of the benchmark {history.instrument} at or before "
            f"{closes[0].isoformat()} to start from"
        )
    with localcontext(_CONTEXT):
        units = starting / _price(bars[start].close)
        paid_through = bars[start].timestamp.date()
        pending = [d for d in history.distributions if d.ex_date > paid_through]
        index = start
        points: list[EquityPoint] = []
        for close in closes:
            while index + 1 < len(bars) and bars[index + 1].timestamp <= close:
                index += 1
                price = _price(bars[index].close)
                day = bars[index].timestamp.date()
                due = [d for d in pending if d.ex_date <= day]
                pending = [d for d in pending if d.ex_date > day]
                per_unit = sum((d.amount_per_share.amount for d in due), Decimal(0))
                units += units * per_unit / price
            value = units * _price(bars[index].close)
            points.append(EquityPoint(close, value, value))
        return tuple(points)


def _price(close: float) -> Decimal:
    """A bar's close as an exact decimal of its shortest representation."""
    return Decimal(repr(close))


def _last_at_or_before(bars: Sequence[Bar], moment: datetime) -> int | None:
    """Index of the last bar stamped at or before ``moment``, or ``None``."""
    found: int | None = None
    for i, bar in enumerate(bars):
        if bar.timestamp > moment:
            break
        found = i
    return found


# --- trades --------------------------------------------------------------------------


def closed_trades(fills: Sequence[Fill]) -> TradeStats:
    """Group fills, in the order they happened, into trades from flat to flat.

    Raises:
        MetricsError: A sale of more than is held, which the ledger never allows.
    """
    held: dict[Instrument, Decimal] = {}
    opened: dict[Instrument, date] = {}
    cash: dict[Instrument, Money] = {}
    closed: list[ClosedTrade] = []
    for fill in fills:
        instrument = fill.instrument
        quantity = held.get(instrument, Decimal(0))
        if fill.side is Side.BUY:
            if quantity == 0:
                opened[instrument] = fill.trade_date
                cash[instrument] = Money.zero(fill.price.currency)
            quantity += fill.quantity
        else:
            if fill.quantity > quantity:
                raise MetricsError(
                    f"fill {fill.fill_id} sells {fill.quantity} {instrument}, "
                    f"but only {quantity} is held"
                )
            quantity -= fill.quantity
        cash[instrument] = cash[instrument] + fill.cash_flow
        held[instrument] = quantity
        if quantity == 0:
            closed.append(
                ClosedTrade(instrument, opened[instrument], fill.trade_date, cash[instrument])
            )
    still_open = sum(1 for quantity in held.values() if quantity > 0)
    return TradeStats(tuple(closed), still_open)


# --- a whole run ---------------------------------------------------------------------


def compare(strategy: SeriesMetrics, benchmark: SeriesMetrics) -> Comparison:
    """The strategy's figures minus the benchmark's."""
    with localcontext(_CONTEXT):
        return Comparison(
            total_return=strategy.total_return - benchmark.total_return,
            cagr=_difference(strategy.cagr, benchmark.cagr),
            volatility=_difference(strategy.volatility, benchmark.volatility),
            sharpe=_difference(strategy.sharpe, benchmark.sharpe),
            sortino=_difference(strategy.sortino, benchmark.sortino),
            max_drawdown=_depth(strategy.max_drawdown) - _depth(benchmark.max_drawdown),
        )


def _difference(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def _depth(drawdown: Drawdown | None) -> Decimal:
    return drawdown.depth if drawdown is not None else Decimal(0)


def measure(
    points: Sequence[EquityPoint],
    fills: Sequence[Fill],
    benchmark: BarHistory,
    currency: Currency,
) -> BacktestMetrics:
    """Measure a run from its equity at every close, its fills and its benchmark's history.

    Takes plain inputs, so a run can be measured from its ``BacktestResult``
    (``measure_backtest``) or from its record's ``equity.csv`` and ``fills.csv``.

    Raises:
        MetricsError: The inputs cannot be measured.
    """
    for fill in fills:
        if fill.price.currency is not currency:
            raise MetricsError(f"fill {fill.fill_id} is in {fill.price.currency}, not {currency}")
    strategy = series_metrics(points)
    curve = benchmark_points(benchmark, [p.at for p in points], points[0].equity)
    bench = series_metrics(curve)
    with localcontext(_CONTEXT):
        traded = sum((fill.gross for fill in fills), Money.zero(currency))
        costs = sum((fill.commission for fill in fills), Money.zero(currency))
        average = _mean([p.equity for p in points])
        turnover = traded.amount / average / strategy.years if strategy.years > 0 else None
    return BacktestMetrics(
        currency=currency,
        benchmark_instrument=benchmark.instrument,
        strategy=strategy,
        benchmark=bench,
        benchmark_equity=curve,
        versus_benchmark=compare(strategy, bench),
        turnover=turnover,
        traded=traded,
        costs=costs,
        trades=closed_trades(fills),
    )


def equity_points(result: BacktestResult, currency: Currency) -> tuple[EquityPoint, ...]:
    """Tyche's account at every session close of a backtest, as equity points."""
    return tuple(
        EquityPoint(
            close.as_of,
            close.account.equity(currency).amount,
            close.account.market_value(currency).amount,
        )
        for close in result.closes
    )


def measure_backtest(result: BacktestResult, currency: Currency) -> BacktestMetrics:
    """Measure a finished (or halted) backtest against its benchmark."""
    return measure(equity_points(result, currency), result.fills, result.benchmark, currency)

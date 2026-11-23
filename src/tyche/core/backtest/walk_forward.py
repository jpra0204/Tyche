"""Walk-forward analysis: folds of history, and the test windows measured as one (ADR-0029).

A walk-forward cuts the history before the holdout into folds. Each fold has a
training window and the test window right after it::

    anchored (the default)           rolling
    train 2005-2009 | test 2010      train 2005-2009 | test 2010
    train 2005-2010 | test 2011      train 2006-2010 | test 2011
    train 2005-2011 | test 2012      train 2007-2011 | test 2012
    ...                              ...

Each window is its own backtest, from the starting cash. Whatever is chosen on a
training window (with a parameter sweep, the parameters with the highest Sharpe ratio;
without one, nothing: the configured strategies are kept, ADR-0030) is then run on the
test window, which it has not seen. A test
window is in-sample for nothing: it is the closest a backtest gets to the future.

This module does no I/O and runs nothing. It plans the folds from dates alone
(``plan_folds``), and measures the finished folds (``measure_walk_forward``): every
fold's training and test results side by side, and the test windows chained into one
out-of-sample equity curve, measured against the benchmark chained the same way.

How windows are cut, chosen once so every walk-forward means the same thing:

* **Windows are whole calendar years**, except that the first training window starts
  on the first day asked for and the last test window ends on the last day asked
  for. With ``train_years = 5`` and a start in 2005, the first test year is 2010
  whatever day of 2005 the history starts: a start late in 2005 gives a shorter
  first training window.
* **Anchored** training windows all start on the first day and grow by one test
  window per fold. **Rolling** ones keep ``train_years`` calendar years.
* **Test windows follow each other with no gap and no overlap**, ``test_years`` each,
  until the last day.

How the test windows are chained: each test window's equity is scaled so that it
starts where the previous one ended. Every window starts in cash and is measured from
its first close, so the session between two windows (the previous window's last close
to the next one's first close) counts as a day with no change, for the strategies and
the benchmark alike.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from tyche.core.backtest.metrics import (
    BacktestMetrics,
    Comparison,
    EquityPoint,
    MetricsError,
    SeriesMetrics,
    compare,
    series_metrics,
)

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class WalkForwardError(ValueError):
    """A walk-forward cannot be planned or measured as asked."""


@dataclass(frozen=True, slots=True)
class Window:
    """A span of days a backtest runs over, both ends included."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.first > self.last:
            raise WalkForwardError(f"empty window: {self.first} is after {self.last}")

    def __str__(self) -> str:
        return f"{self.first.isoformat()} to {self.last.isoformat()}"


@dataclass(frozen=True, slots=True)
class FoldScheme:
    """How the history is cut into folds.

    Attributes:
        train_years: Calendar years in the first training window, and in every one
            when the windows roll.
        test_years: Calendar years in each test window.
        anchored: True if every training window starts on the first day (it grows);
            False if it keeps ``train_years`` and rolls forward.
    """

    train_years: int = 5
    test_years: int = 1
    anchored: bool = True

    def __post_init__(self) -> None:
        if self.train_years < 1:
            raise WalkForwardError(f"train_years must be at least 1, got {self.train_years}")
        if self.test_years < 1:
            raise WalkForwardError(f"test_years must be at least 1, got {self.test_years}")

    def __str__(self) -> str:
        kind = "anchored" if self.anchored else "rolling"
        train = f"{self.train_years}-year" + (" first" if self.anchored else "")
        return f"{kind}: {train} training window, {self.test_years}-year test windows"


@dataclass(frozen=True, slots=True)
class Fold:
    """One training window and the test window right after it.

    Attributes:
        number: From 1, in time order.
        train: Where the training is done.
        test: Where what the training chose is tried, on days it has not seen.
    """

    number: int
    train: Window
    test: Window


def plan_folds(first: date, last: date, scheme: FoldScheme) -> tuple[Fold, ...]:
    """Cut ``first`` to ``last`` into folds, as the module docstring describes.

    Raises:
        WalkForwardError: The range leaves no test window after the first training one.
    """
    if first > last:
        raise WalkForwardError(f"empty range: {first} is after {last}")
    folds: list[Fold] = []
    test_year = first.year + scheme.train_years
    while date(test_year, 1, 1) <= last:
        train_from = (
            first if scheme.anchored else max(first, date(test_year - scheme.train_years, 1, 1))
        )
        test_to = min(last, date(test_year + scheme.test_years - 1, 12, 31))
        folds.append(
            Fold(
                number=len(folds) + 1,
                train=Window(train_from, date(test_year - 1, 12, 31)),
                test=Window(date(test_year, 1, 1), test_to),
            )
        )
        test_year += scheme.test_years
    if not folds:
        raise WalkForwardError(
            f"{first} to {last} leaves no test window after a {scheme.train_years}-year "
            f"training window: the first test window would start on "
            f"{date(first.year + scheme.train_years, 1, 1)}"
        )
    return tuple(folds)


@dataclass(frozen=True, slots=True)
class FoldResult:
    """One finished fold.

    Attributes:
        fold: Its windows.
        train: The training window's run, measured against the benchmark.
        test: The test window's run, measured against the benchmark.
        test_equity: The test window's equity at every close, for chaining.
    """

    fold: Fold
    train: BacktestMetrics
    test: BacktestMetrics
    test_equity: tuple[EquityPoint, ...]


@dataclass(frozen=True, slots=True)
class WalkForwardMetrics:
    """A whole walk-forward: each fold, and the test windows chained into one.

    Attributes:
        folds: Every fold, in time order.
        equity: The test windows' equity chained, from the first test window's start.
        benchmark_equity: The benchmark over the same test windows, chained the same way.
        out_of_sample: ``equity`` measured.
        benchmark: ``benchmark_equity`` measured.
        versus_benchmark: Out-of-sample minus benchmark.
        tests_ahead: Test windows whose total return beat the benchmark's.
    """

    folds: tuple[FoldResult, ...]
    equity: tuple[EquityPoint, ...]
    benchmark_equity: tuple[EquityPoint, ...]
    out_of_sample: SeriesMetrics
    benchmark: SeriesMetrics
    versus_benchmark: Comparison
    tests_ahead: int


def chain(segments: Sequence[Sequence[EquityPoint]]) -> tuple[EquityPoint, ...]:
    """Join equity curves end to end, each scaled to start where the previous one ended.

    The first segment is kept as it is. Equity and the invested amount are scaled
    alike, so the share invested at every close is unchanged.

    Raises:
        MetricsError: No segment, an empty one, or segments that overlap in time.
    """
    if not segments:
        raise MetricsError("no equity to chain")
    chained: list[EquityPoint] = []
    with localcontext(_CONTEXT):
        for segment in segments:
            if not segment:
                raise MetricsError("cannot chain an empty equity curve")
            if chained and segment[0].at <= chained[-1].at:
                raise MetricsError(
                    f"equity curves overlap: one starts at {segment[0].at.isoformat()}, "
                    f"before the previous one ends at {chained[-1].at.isoformat()}"
                )
            scale = chained[-1].equity / segment[0].equity if chained else Decimal(1)
            chained.extend(EquityPoint(p.at, p.equity * scale, p.invested * scale) for p in segment)
    return tuple(chained)


def measure_walk_forward(folds: Sequence[FoldResult]) -> WalkForwardMetrics:
    """Measure finished folds: the test windows chained, against the benchmark chained.

    Raises:
        MetricsError: No fold, or test windows that are not in time order.
    """
    if not folds:
        raise MetricsError("no fold to measure")
    ordered = tuple(folds)
    equity = chain([f.test_equity for f in ordered])
    benchmark_equity = chain([f.test.benchmark_equity for f in ordered])
    out_of_sample = series_metrics(equity)
    benchmark = series_metrics(benchmark_equity)
    return WalkForwardMetrics(
        folds=ordered,
        equity=equity,
        benchmark_equity=benchmark_equity,
        out_of_sample=out_of_sample,
        benchmark=benchmark,
        versus_benchmark=compare(out_of_sample, benchmark),
        tests_ahead=sum(1 for f in ordered if f.test.versus_benchmark.total_return > 0),
    )

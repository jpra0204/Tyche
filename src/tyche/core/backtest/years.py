"""Returns by calendar year, for a run and its benchmark (ADR-0028).

A year's return runs from the last close of the year before to the year's last close,
so the years chain: compounding them gives the run's total return. The first year
starts from the run's first close, and the first and last years are usually partial;
each ``YearReturn`` says which closes it covers, so a report can show that.

A close belongs to the calendar year of its UTC date, which is its trading day for
the US, whose sessions close before midnight UTC (the same limit as the benchmark's
dates, in the backtesting internals' known limits).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import groupby

from tyche.core.backtest.metrics import EquityPoint, MetricsError

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class YearReturn:
    """One calendar year of a run.

    Attributes:
        year: The calendar year.
        first: The first close in the year.
        last: The last close in the year.
        value: Equity at ``last`` over equity at the close before the year (or at the
            run's first close, for its first year), minus one.
    """

    year: int
    first: datetime
    last: datetime
    value: Decimal


def yearly_returns(points: Sequence[EquityPoint]) -> tuple[YearReturn, ...]:
    """The return of each calendar year that ``points`` (oldest first) touch."""
    if not points:
        raise MetricsError("no equity to measure")
    years: list[YearReturn] = []
    with localcontext(_CONTEXT):
        start = points[0].equity
        for year, group in groupby(points, key=lambda p: p.at.year):
            closes = list(group)
            years.append(
                YearReturn(year, closes[0].at, closes[-1].at, closes[-1].equity / start - 1)
            )
            start = closes[-1].equity
    return tuple(years)

"""Returns by calendar year: they chain into the run's total return."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tyche.core.backtest import EquityPoint, MetricsError, YearReturn, yearly_returns


def point(year: int, month: int, day: int, equity: str) -> EquityPoint:
    return EquityPoint(datetime(year, month, day, 21, tzinfo=UTC), Decimal(equity), Decimal(0))


def test_each_year_runs_from_the_last_close_of_the_year_before() -> None:
    points = [
        point(2022, 11, 1, "1000"),
        point(2022, 12, 30, "1100"),
        point(2023, 6, 1, "990"),
        point(2023, 12, 29, "1210"),
        point(2024, 1, 2, "1331"),
    ]

    years = yearly_returns(points)

    assert years == (
        YearReturn(2022, points[0].at, points[1].at, Decimal("0.1")),
        YearReturn(2023, points[2].at, points[3].at, Decimal("0.1")),
        YearReturn(2024, points[4].at, points[4].at, Decimal("0.1")),
    )
    growth = Decimal(1)
    for year in years:
        growth *= 1 + year.value
    assert growth - 1 == Decimal("1.331") - 1


def test_nothing_to_measure() -> None:
    with pytest.raises(MetricsError):
        yearly_returns([])

"""Cost drag: costs added back onto equity, and the run measured both ways."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tyche.core.backtest import EquityPoint, FillCost, MetricsError, cost_drag, fill_cost
from tyche.core.domain import Side

OPEN = datetime(2024, 1, 3, 14, 30, tzinfo=UTC)


def close(day: int, equity: str) -> EquityPoint:
    return EquityPoint(datetime(2024, 1, day, 21, 0, tzinfo=UTC), Decimal(equity), Decimal(0))


def test_slippage_is_worked_back_from_the_fill_price() -> None:
    # 5 bps: a buy at 100.05 had a reference of 100.05 / 1.0005 = 100.
    buy = fill_cost(OPEN, Side.BUY, Decimal(10), Decimal("100.05"), Decimal("1.00"), Decimal(5))
    # A sale at 99.95 had a reference of 99.95 / 0.9995 = 100.
    sale = fill_cost(OPEN, Side.SELL, Decimal(10), Decimal("99.95"), Decimal("1.00"), Decimal(5))

    assert buy == FillCost(OPEN, Decimal("1.00"), Decimal("0.5"))
    assert sale == FillCost(OPEN, Decimal("1.00"), Decimal("0.5"))
    assert sale.total == Decimal("1.5")


def test_costs_are_added_back_from_the_first_close_after_they_were_paid() -> None:
    points = [close(2, "1000"), close(3, "998"), close(4, "1008")]
    costs = [FillCost(OPEN, Decimal("1.00"), Decimal("0.50"))]

    drag = cost_drag(points, costs)

    assert [p.equity for p in drag.before_costs_points] == [
        Decimal(1000),
        Decimal("999.50"),
        Decimal("1009.50"),
    ]
    assert (drag.commission, drag.slippage, drag.total) == (
        Decimal("1.00"),
        Decimal("0.50"),
        Decimal("1.50"),
    )
    assert drag.after_costs.total_return == Decimal("0.008")
    assert drag.before_costs.total_return == Decimal("0.0095")
    # Gross profit 9.50, of which 1.50 went on costs.
    assert drag.share_of_gross_profit == Decimal("1.50") / Decimal("9.50")


def test_the_drag_is_the_difference_in_cagr() -> None:
    points = [
        EquityPoint(datetime(2023, 1, 3, 21, tzinfo=UTC), Decimal(1000), Decimal(0)),
        EquityPoint(datetime(2024, 1, 3, 21, tzinfo=UTC), Decimal(1090), Decimal(0)),
    ]
    paid = FillCost(datetime(2023, 6, 1, 14, 30, tzinfo=UTC), Decimal(10), Decimal(0))

    drag = cost_drag(points, [paid])

    assert drag.after_costs.cagr is not None
    assert drag.before_costs.cagr is not None
    assert drag.cagr_drag == drag.before_costs.cagr - drag.after_costs.cagr
    assert drag.cagr_drag == pytest.approx(Decimal("0.01"), abs=Decimal("0.0001"))
    # 10 paid in about a year, on an average equity of 1045.
    assert drag.per_year == pytest.approx(Decimal(10) / Decimal(1045), rel=Decimal("0.01"))


def test_no_gross_profit_means_no_share() -> None:
    points = [close(2, "1000"), close(4, "990")]

    drag = cost_drag(points, [FillCost(OPEN, Decimal("1.00"), Decimal(0))])

    assert drag.share_of_gross_profit is None


def test_no_costs_means_no_drag() -> None:
    points = [close(2, "1000"), close(4, "1010")]

    drag = cost_drag(points, [])

    assert drag.total == 0
    assert drag.before_costs == drag.after_costs
    assert drag.cagr_drag == 0


def test_a_cost_after_the_last_close_is_refused() -> None:
    late = FillCost(datetime(2024, 1, 5, 14, 30, tzinfo=UTC), Decimal(1), Decimal(0))

    with pytest.raises(MetricsError, match="after the last close"):
        cost_drag([close(2, "1000"), close(4, "1010")], [late])


def test_negative_costs_are_refused() -> None:
    with pytest.raises(MetricsError, match="negative"):
        FillCost(OPEN, Decimal(-1), Decimal(0))

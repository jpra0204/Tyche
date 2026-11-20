"""Cost drag: what trading costs took from a backtest (ADR-0028).

Measured from the run's own record, not from a second simulation. Every cost paid up
to a close is added back onto the equity at that close, which gives a **before-costs**
equity curve, and the run is measured on both curves the same way (``series_metrics``).

The costs added back:

* **Commission and regulatory fees**, as each fill recorded them.
* **Slippage**: how far each fill's price moved against the order from its reference
  price at the configured rate (ADR-0020). A buy filled at ``price`` had a reference
  of ``price / (1 + s)``, a sale ``price / (1 - s)``; the slippage is the quantity
  times the difference.

The costs are added back as paid, not compounded. Money not spent on costs would have
been invested and grown too, so the before-costs curve is a little low, and the drag a
little understated. On a small account, where costs are large next to returns, read
it as a floor.

Arithmetic is ``Decimal`` in a fixed context, as for the metrics.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from tyche.core.backtest.metrics import EquityPoint, MetricsError, SeriesMetrics, series_metrics
from tyche.core.domain import Side
from tyche.core.domain.costs import BASIS_POINT
from tyche.core.domain.validation import require_utc

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class FillCost:
    """What one fill cost on top of its reference price.

    Attributes:
        at: When it filled, in UTC.
        commission: Commission and regulatory fees, as the fill recorded them.
        slippage: The price's move against the order, times the quantity.
    """

    at: datetime
    commission: Decimal
    slippage: Decimal

    def __post_init__(self) -> None:
        require_utc(self.at, "FillCost at")
        if self.commission < 0 or self.slippage < 0:
            raise MetricsError(f"the costs of the fill at {self.at.isoformat()} are negative")

    @property
    def total(self) -> Decimal:
        return self.commission + self.slippage


def fill_cost(
    at: datetime,
    side: Side,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal,
    slippage_bps: Decimal,
) -> FillCost:
    """The costs of one fill, its slippage worked back from its price."""
    with localcontext(_CONTEXT):
        rate = slippage_bps * BASIS_POINT
        if side is Side.BUY:
            reference = price / (1 + rate)
            slippage = quantity * (price - reference)
        else:
            reference = price / (1 - rate)
            slippage = quantity * (reference - price)
        return FillCost(at, commission, slippage)


@dataclass(frozen=True, slots=True)
class CostDrag:
    """A run measured after and before its costs.

    Attributes:
        commission: Commission and regulatory fees paid over the run.
        slippage: Slippage paid over the run.
        after_costs: The run as it happened.
        before_costs: The run with every cost paid to date added back at each close.
        before_costs_points: The before-costs equity at every close.
        per_year: Costs per year as a fraction of the average equity, or ``None`` for
            a run shorter than a day.
        share_of_gross_profit: Costs as a fraction of the profit before costs, or
            ``None`` if there was no profit before costs.
    """

    commission: Decimal
    slippage: Decimal
    after_costs: SeriesMetrics
    before_costs: SeriesMetrics
    before_costs_points: tuple[EquityPoint, ...]
    per_year: Decimal | None
    share_of_gross_profit: Decimal | None

    @property
    def total(self) -> Decimal:
        return self.commission + self.slippage

    @property
    def cagr_drag(self) -> Decimal | None:
        """CAGR before costs minus CAGR after: what the costs cost each year."""
        before, after = self.before_costs.cagr, self.after_costs.cagr
        return None if before is None or after is None else before - after


def cost_drag(points: Sequence[EquityPoint], costs: Sequence[FillCost]) -> CostDrag:
    """Measure ``points`` (every session close, oldest first) before and after ``costs``.

    A cost counts from the first close at or after it was paid.
    """
    if not points:
        raise MetricsError("no equity to measure")
    ordered = sorted(costs, key=lambda cost: cost.at)
    with localcontext(_CONTEXT):
        before: list[EquityPoint] = []
        paid, next_cost = Decimal(0), 0
        for point in points:
            while next_cost < len(ordered) and ordered[next_cost].at <= point.at:
                paid += ordered[next_cost].total
                next_cost += 1
            before.append(EquityPoint(point.at, point.equity + paid, point.invested))
        if next_cost < len(ordered):
            raise MetricsError("a cost was paid after the last close of the run")

        after_costs = series_metrics(points)
        before_costs = series_metrics(before)
        commission = sum((cost.commission for cost in ordered), Decimal(0))
        slippage = sum((cost.slippage for cost in ordered), Decimal(0))
        total = commission + slippage
        average = sum((p.equity for p in points), Decimal(0)) / len(points)
        per_year = total / average / after_costs.years if after_costs.years > 0 else None
        gross_profit = before[-1].equity - points[0].equity
        share = total / gross_profit if gross_profit > 0 else None
        return CostDrag(
            commission=commission,
            slippage=slippage,
            after_costs=after_costs,
            before_costs=before_costs,
            before_costs_points=tuple(before),
            per_year=per_year,
            share_of_gross_profit=share,
        )

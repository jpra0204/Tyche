"""Trading costs: commission, regulatory fees, slippage and settlement (ADR-0020).

The rates are data, loaded from the workspace (``config/costs/<PROFILE>.toml``), never
written into code: a broker changes its prices, and a backtest must say which prices it
used. Each ``TradingCosts`` carries the date its rates were checked against the
broker's published schedule.

The arithmetic is here, in the domain, because it is pure and because more than the
simulator needs it: order sizing must know what a purchase will really cost, and the
minimum-viable-capital analysis (PR 22) asks the same question in reverse.

Rounding is explicit and follows one rule: **when unsure, overstate the cost.**

* The commission is rounded to the cent, halves to even. IBKR's published examples are
  all whole cents; how it rounds anything finer is not published (not verified).
* Regulatory fees are rounded **up** to the cent. They are fractions of a cent on a
  small order, and how IBKR rounds them is not published either.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from tyche.core.domain.currency import Currency
from tyche.core.domain.money import Money
from tyche.core.domain.order import Side

CENT_PLACES = 2
_CENT = Decimal("0.01")
BASIS_POINT = Decimal("0.0001")


def _require_rate(value: Decimal, what: str, *, at_most: Decimal | None = None) -> None:
    if not value.is_finite() or value < 0:
        raise ValueError(f"{what} must be zero or more, got {value}")
    if at_most is not None and value > at_most:
        raise ValueError(f"{what} must be at most {at_most}, got {value}")


def _require_trade(quantity: Decimal, price: Money, currency: Currency) -> None:
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if not price.is_positive:
        raise ValueError(f"price must be positive, got {price}")
    if price.currency is not currency:
        raise ValueError(f"price is in {price.currency}, but these costs are in {currency}")


@dataclass(frozen=True, slots=True)
class CommissionSchedule:
    """A per-share commission with a minimum and a maximum per order.

    This is the shape of IBKR Pro Fixed: ``min(max(per_share * shares, minimum),
    maximum_rate * trade value)``. When the maximum is below the minimum, the maximum
    wins, as IBKR's own example shows (10 shares of a USD 0.20 stock cost USD 0.02).

    Attributes:
        per_share: Charged for each share, e.g. USD 0.005.
        minimum: The least an order costs, e.g. USD 1.00.
        maximum_rate: The most an order costs, as a fraction of its value, e.g. 0.01
            for 1%.
    """

    per_share: Money
    minimum: Money
    maximum_rate: Decimal

    def __post_init__(self) -> None:
        if self.minimum.currency is not self.per_share.currency:
            raise ValueError("commission: per_share and minimum must be in the same currency")
        _require_rate(self.per_share.amount, "commission per_share")
        _require_rate(self.minimum.amount, "commission minimum")
        _require_rate(self.maximum_rate, "commission maximum_rate", at_most=Decimal(1))

    @property
    def currency(self) -> Currency:
        return self.per_share.currency

    def commission(self, quantity: Decimal, price: Money) -> Money:
        """The commission on one order of ``quantity`` shares at ``price``, to the cent."""
        _require_trade(quantity, price, self.currency)
        by_shares = max(self.per_share * quantity, self.minimum)
        cap = price * quantity * self.maximum_rate
        return min(by_shares, cap).round_to(CENT_PLACES)


@dataclass(frozen=True, slots=True)
class RegulatoryFees:
    """Fees the regulators charge and the broker passes on, under every pricing plan.

    Attributes:
        sec_fee_rate: SEC transaction fee, a fraction of the value of each sale.
        taf_per_share_sold: FINRA Trading Activity Fee, per share sold.
        cat_per_share: FINRA Consolidated Audit Trail fee, per share, buys and sells.
    """

    sec_fee_rate: Decimal
    taf_per_share_sold: Money
    cat_per_share: Money

    def __post_init__(self) -> None:
        if self.cat_per_share.currency is not self.taf_per_share_sold.currency:
            raise ValueError("regulatory fees must all be in the same currency")
        _require_rate(self.sec_fee_rate, "sec_fee_rate", at_most=Decimal(1))
        _require_rate(self.taf_per_share_sold.amount, "taf_per_share_sold")
        _require_rate(self.cat_per_share.amount, "cat_per_share")

    @property
    def currency(self) -> Currency:
        return self.cat_per_share.currency

    def fees(self, side: Side, quantity: Decimal, price: Money) -> Money:
        """The fees on one order, rounded up to the cent."""
        _require_trade(quantity, price, self.currency)
        total = self.cat_per_share * quantity
        if side is Side.SELL:
            total = total + price * quantity * self.sec_fee_rate
            total = total + self.taf_per_share_sold * quantity
        return Money(total.amount.quantize(_CENT, ROUND_CEILING), total.currency)


@dataclass(frozen=True, slots=True)
class TradeCost:
    """What one order costs on top of its price.

    Attributes:
        commission: The broker's commission.
        regulatory_fees: Fees passed on from regulators.
    """

    commission: Money
    regulatory_fees: Money

    @property
    def total(self) -> Money:
        """Everything charged. A ``Fill`` records this as its commission."""
        return self.commission + self.regulatory_fees


@dataclass(frozen=True, slots=True)
class TradingCosts:
    """What it costs to trade in one currency, in money and in time.

    Attributes:
        commission: The broker's commission schedule.
        regulatory_fees: Fees passed on from regulators.
        slippage_bps: How far a simulated fill moves against the order, in basis points
            of the reference price. A modelling assumption, not a broker fact; every
            report states the value used.
        settlement_days: Sessions between a trade and its settlement: 1 for T+1. In a
            cash account, sale proceeds cannot be spent until then (ADR-0020).
        checked_on: When the rates were last checked against the broker's published
            schedule.
    """

    commission: CommissionSchedule
    regulatory_fees: RegulatoryFees
    slippage_bps: Decimal
    settlement_days: int
    checked_on: date

    def __post_init__(self) -> None:
        if self.regulatory_fees.currency is not self.commission.currency:
            raise ValueError(
                f"costs: commission is in {self.commission.currency}, "
                f"regulatory fees in {self.regulatory_fees.currency}"
            )
        # 10,000 basis points is 100%: a buy at double the price, a sale for nothing.
        _require_rate(self.slippage_bps, "slippage_bps", at_most=Decimal(10_000))
        if self.settlement_days < 0:
            raise ValueError(f"settlement_days must be zero or more, got {self.settlement_days}")

    @property
    def currency(self) -> Currency:
        return self.commission.currency

    def cost_of(self, side: Side, quantity: Decimal, price: Money) -> TradeCost:
        """The commission and fees on one order of ``quantity`` shares at ``price``."""
        return TradeCost(
            commission=self.commission.commission(quantity, price),
            regulatory_fees=self.regulatory_fees.fees(side, quantity, price),
        )

    def fill_price(self, side: Side, reference: Money) -> Money:
        """The simulated fill price: ``reference`` moved against the order by the slippage.

        A buy pays more and a sale receives less, never the other way round.
        """
        _require_trade(Decimal(1), reference, self.currency)
        move = self.slippage_bps * BASIS_POINT
        if side is Side.BUY:
            return reference * (1 + move)
        return reference * (1 - move)


def whole_shares(budget: Money, price: Money) -> Decimal:
    """The most whole shares ``budget`` buys at ``price``, ignoring costs. Zero if none.

    Tyche trades whole shares only, because IBKR's API cannot place fractional orders
    (ADR-0020). A target worth less than one share is not held at all, and the caller
    records that it was dropped.
    """
    if budget.currency is not price.currency:
        raise ValueError(f"budget is in {budget.currency}, price in {price.currency}")
    if not price.is_positive:
        raise ValueError(f"price must be positive, got {price}")
    if not budget.is_positive:
        return Decimal(0)
    return (budget / price).quantize(Decimal(1), ROUND_FLOOR)


def affordable_shares(cash: Money, reference: Money, costs: TradingCosts) -> Decimal:
    """The most whole shares ``cash`` pays for, after slippage, commission and fees.

    Used to size a purchase from settled cash, so that the order the broker receives is
    one the account can pay for in full.
    """
    price = costs.fill_price(Side.BUY, reference)
    shares = whole_shares(cash, price)
    # Before costs, ``shares`` fit in ``cash``, so the shortfall is at most the costs.
    # Each step back frees at least one share's price, and costs never rise when the
    # order shrinks, so the loop ends within (costs / price) + 1 steps.
    while shares > 0:
        needed = price * shares + costs.cost_of(Side.BUY, shares, price).total
        if needed <= cash:
            return shares
        shares -= 1
    return Decimal(0)

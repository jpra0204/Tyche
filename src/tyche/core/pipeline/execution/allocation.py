"""Two pure allocation rules execution relies on (ADR-0023).

* ``split_pro_rata``: share whole shares between sleeves in proportion to what each is
  owed. Used for crossing between sleeves, for a netted fill, and for a purchase cut to
  the cash available.
* ``fit_to_cash``: shrink a cycle's purchases, in proportion, until settled cash pays
  for all of them, costs included.

Both work in whole shares and are exact: integers for the proportions, ``Decimal`` for
the money. Ties are broken by a fixed order, so the same inputs always give the same
answer.
"""

from collections.abc import Mapping
from decimal import ROUND_FLOOR, Decimal

from tyche.core.domain import Instrument, Money, Side, TradingCosts


def _whole(value: Decimal, what: str) -> int:
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise ValueError(f"{what} must be a whole number of shares, got {value}")
    return int(value)


def split_pro_rata(total: Decimal, needs: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Split ``total`` whole shares between ``needs``, in proportion to each need.

    Each gets the whole part of its exact share; the shares left over go one each to
    the largest remainders, ties to the earlier key. Nobody gets more than its need.

    Args:
        total: Shares to split. At most the sum of ``needs``.
        needs: Whole shares owed, by strategy id. Every need is positive.

    Returns:
        Shares given, for every key of ``needs`` (zero included).
    """
    owed = {key: _whole(need, f"need of {key}") for key, need in needs.items()}
    if any(need == 0 for need in owed.values()):
        raise ValueError("every need must be positive")
    shares = _whole(total, "total")
    owed_total = sum(owed.values())
    if shares > owed_total:
        raise ValueError(f"cannot split {shares} shares between needs adding up to {owed_total}")
    if shares == 0:
        return {key: Decimal(0) for key in owed}

    given = {key: shares * need // owed_total for key, need in owed.items()}
    remainders = {key: shares * need % owed_total for key, need in owed.items()}
    left = shares - sum(given.values())
    for key in sorted(owed, key=lambda k: (-remainders[k], k))[:left]:
        given[key] += 1
    return {key: Decimal(value) for key, value in given.items()}


def _key(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, instrument.exchange


def purchase_cost(quantity: Decimal, reference: Money, costs: TradingCosts) -> Money:
    """What buying ``quantity`` shares at ``reference`` takes from cash, all costs included."""
    if quantity == 0:
        return Money.zero(reference.currency)
    price = costs.fill_price(Side.BUY, reference)
    return price * quantity + costs.cost_of(Side.BUY, quantity, price).total


def fit_to_cash(
    wanted: Mapping[Instrument, Decimal],
    references: Mapping[Instrument, Money],
    costs: TradingCosts,
    cash: Money,
) -> dict[Instrument, Decimal]:
    """Shrink purchases until ``cash`` pays for all of them, after slippage and costs.

    If they already fit, they are returned unchanged. Otherwise each is scaled down in
    proportion to the cash, rounded down to whole shares; then, while they still do not
    fit (minimum commissions do not scale), the largest is cut by one share at a time,
    ties to the first by symbol and exchange.

    Args:
        wanted: Whole shares to buy, by instrument, all in ``cash``'s currency.
        references: The price to cost each purchase at, by instrument.
        costs: Slippage, commission and fees.
        cash: What there is to spend.
    """
    for instrument, quantity in wanted.items():
        _whole(quantity, f"purchase of {instrument}")

    def needed(plan: Mapping[Instrument, Decimal]) -> Money:
        total = Money.zero(cash.currency)
        for instrument, quantity in plan.items():
            total += purchase_cost(quantity, references[instrument], costs)
        return total

    full = needed(wanted)
    if full <= cash:
        return dict(wanted)
    if not cash.is_positive:
        return {instrument: Decimal(0) for instrument in wanted}

    ratio = cash / full
    plan = {
        instrument: (quantity * ratio).quantize(Decimal(1), ROUND_FLOOR)
        for instrument, quantity in wanted.items()
    }
    while needed(plan) > cash:
        largest = max(sorted(plan, key=_key), key=lambda i: plan[i])
        plan[largest] -= 1
    return plan

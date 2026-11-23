"""Minimum viable capital: the account size at which a strategy's edge survives costs (ADR-0031).

A small account pays more for the same trades, for two reasons. The broker's
minimum commission is a large fraction of a small order, and whole shares leave part
of every small target unheld (ADR-0020). Both fade as the account grows, so the same
strategy run on a large **reference** account shows what it earns when its size no
longer matters.

The test (ADR-0031): the **size penalty** of an amount is the reference run's CAGR
minus that amount's CAGR, both after costs. An amount is **viable** when its penalty
is within a tolerance either way, such as half a point a year. A small account that
does much *better* than the large one is not viable either: whole shares made it run
a different strategy, and its lead is luck in when it could afford a share (a small
account that buys its first share in a crash rides the recovery fully invested).

The **minimum viable capital** is the smallest tested amount from which every larger
tested amount is viable too: one lucky amount below a failing one does not count.

The test says what account size costs. It does not say whether there is an edge to
keep: that is whether the strategy beats its benchmark, reported beside it.

Pure arithmetic: no I/O, and ``Decimal`` throughout, like the metrics.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from tyche.core.domain.costs import TradingCosts, affordable_shares
from tyche.core.domain.money import Money
from tyche.core.domain.order import Side


class CapitalError(ValueError):
    """A capital analysis cannot be set up as asked."""


@dataclass(frozen=True, slots=True)
class SizedResult:
    """One strategy's CAGR, after costs, on one account size.

    Attributes:
        amount: The starting cash.
        cagr: The CAGR after costs; ``None`` if the run could not be measured.
    """

    amount: Decimal
    cagr: Decimal | None


def size_penalty(cagr: Decimal | None, reference: Decimal | None) -> Decimal | None:
    """The reference account's CAGR minus ``cagr``; ``None`` if either is ``None``.

    Positive when the smaller account earns less, which is the usual case.
    """
    if cagr is None or reference is None:
        return None
    return reference - cagr


def is_viable(cagr: Decimal | None, reference: Decimal | None, tolerance: Decimal) -> bool:
    """True if the size penalty is within ``tolerance`` either way.

    An unmeasured run is not viable.
    """
    penalty = size_penalty(cagr, reference)
    return penalty is not None and abs(penalty) <= tolerance


def minimum_viable(
    results: Sequence[SizedResult], reference: Decimal | None, tolerance: Decimal
) -> Decimal | None:
    """The smallest amount from which every larger amount in ``results`` is viable.

    ``None`` when the largest amount tested is not viable, or nothing was measured
    on the reference account: no tested size is then known to be enough.

    Raises:
        CapitalError: ``results`` is empty, repeats an amount, or ``tolerance`` is
            negative.
    """
    if not results:
        raise CapitalError("no amounts to test")
    if tolerance < 0:
        raise CapitalError(f"the tolerance must be zero or more, got {tolerance}")
    amounts = [r.amount for r in results]
    if len(set(amounts)) != len(amounts):
        raise CapitalError("each amount may be tested once")
    smallest: Decimal | None = None
    for result in sorted(results, key=lambda r: r.amount, reverse=True):
        if not is_viable(result.cagr, reference, tolerance):
            break
        smallest = result.amount
    return smallest


def round_trip_cost(costs: TradingCosts, position: Money, price: Money) -> Decimal | None:
    """What buying ``position``'s worth of shares at ``price`` and selling them costs.

    As a fraction of the shares' value: commission and fees on both orders, and the
    slippage on both, at ``price`` both times. The shares are sized as execution sizes
    a purchase, from cash with room for the costs (``affordable_shares``). ``None`` if
    the position cannot buy one whole share.
    """
    shares = affordable_shares(position, price, costs)
    if shares == 0:
        return None
    bought = costs.fill_price(Side.BUY, price)
    sold = costs.fill_price(Side.SELL, price)
    paid = (
        costs.cost_of(Side.BUY, shares, bought).total
        + costs.cost_of(Side.SELL, shares, sold).total
        + (bought - sold) * shares
    )
    return paid.amount / (price * shares).amount

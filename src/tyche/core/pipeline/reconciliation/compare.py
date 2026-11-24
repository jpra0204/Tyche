"""The comparison: a checkpoint against the broker's record (ADR-0044).

A pure function. It reads Tyche's records as a checkpoint holds them (the account,
the sleeve book, execution's working orders, and reconciliation's memory) and the
broker's ``BrokerRecord``, and says what agrees, what Tyche should correct, and what
halts. It changes nothing: ``correct`` and ``resolve`` apply its findings.

The rules, in the order they are applied:

1. **Orders.** Every order the broker lists as working must be one Tyche expects,
   with the same shares remaining; no working order in the account may be anyone
   else's. An expected order the broker no longer lists is *missing*.
2. **Positions, exact.** For each instrument, the broker's shares less Tyche's:
   * no difference: its missing orders *ended* with no shares moved;
   * a difference that exactly one missing order explains (its side and remaining
     shares) is a fill on a day no run read, if its price can be inferred (3);
   * anything else is a difference.
3. **Cash, per currency Tyche trades in.** The *gap* is the broker's total cash plus
   its accrued dividends, less Tyche's total cash. With one inferred fill in the
   currency, the gap prices it (commission folded in). Otherwise the gap is accepted
   up to the tolerance plus the dividends on their way: those Tyche credited since the
   last check, and those the broker had accrued then. Beyond that, it is a difference.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from tyche.core.domain import (
    Account,
    BrokerRecord,
    CashCheck,
    CashOutcome,
    Checkpoint,
    Currency,
    Difference,
    DifferenceKind,
    EndedOrder,
    InferredFill,
    Instrument,
    Money,
    Reconciliation,
    ReconciliationRules,
    ReconciliationState,
    Side,
    WorkingOrder,
)

PRICE_PLACES = 6
"""Decimal places of an inferred price: finer than any real price, so the cash it
implies is the gap it came from to well under a cent."""


def reconcile(
    checkpoint: Checkpoint,
    broker: BrokerRecord,
    rules: ReconciliationRules,
    currencies: Iterable[Currency],
    at: datetime,
) -> Reconciliation:
    """Compare Tyche's records in ``checkpoint`` with ``broker``'s, as of ``at``.

    Args:
        checkpoint: Tyche's records, after every fill the broker reported was applied.
        broker: The broker's record, read at the same moment.
        rules: The market profile's ``[reconciliation]`` table.
        currencies: The currencies Tyche trades in: the profile's cash currencies.
            Cash in any other currency is not compared (Phase 4 adds them).
        at: When the comparison is made.
    """
    account = checkpoint.account
    traded = tuple(currencies)
    differences: list[Difference] = [
        Difference(DifferenceKind.UNRESOLVED, "broker", note) for note in broker.unresolved
    ]
    if broker.foreign_orders:
        differences.append(
            Difference(
                DifferenceKind.FOREIGN_ORDER,
                "account",
                f"{broker.foreign_orders} working order(s) in the account are not Tyche's",
            )
        )

    expected = {o.state.order.client_order_id: o for o in checkpoint.execution.orders}
    missing: dict[Instrument, list[WorkingOrder]] = defaultdict(list)
    listed = {o.client_order_id: o for o in broker.orders}
    for order_id in sorted(listed):
        working = expected.get(order_id)
        remaining = listed[order_id].remaining
        if working is None:
            differences.append(
                Difference(
                    DifferenceKind.UNKNOWN_ORDER,
                    order_id,
                    f"the broker has it working with {remaining} shares to fill; Tyche does "
                    "not expect it",
                )
            )
        elif working.state.remaining != remaining:
            differences.append(
                Difference(
                    DifferenceKind.ORDER,
                    order_id,
                    f"Tyche expects {working.state.remaining} shares to fill, the broker "
                    f"{remaining}",
                )
            )
    for order_id in sorted(expected):
        if order_id not in listed:
            working = expected[order_id]
            missing[working.state.order.instrument].append(working)

    ours = {p.instrument: p.quantity for p in account.positions}
    theirs = {p.instrument: p.quantity for p in broker.account.positions}
    ended: list[EndedOrder] = []
    explaining: dict[Currency, list[WorkingOrder]] = defaultdict(list)
    for instrument in sorted(set(ours) | set(theirs) | set(missing), key=str):
        held = ours.get(instrument, Decimal(0))
        reported = theirs.get(instrument, Decimal(0))
        gone = missing.get(instrument, [])
        moved = reported - held
        if moved == 0:
            ended.extend(_ended(o) for o in gone)
            continue
        if len(gone) == 1 and _signed(gone[0]) == moved and instrument.currency in traded:
            explaining[instrument.currency].append(gone[0])
            continue
        differences.append(_position(instrument, held, reported, gone))

    inferred: list[InferredFill] = []
    checks: list[CashCheck] = []
    for currency in traded:
        tyche = account.cash(currency).total
        cash = broker.account.cash(currency)
        accrued = broker.accrued(currency)
        allowed = _allowed(rules, checkpoint.reconciliation, account, currency)
        gap = cash.total + accrued - tyche
        orders = explaining.get(currency, [])
        fill = _inferred(orders[0], gap) if len(orders) == 1 else None
        if fill is not None:
            inferred.append(fill)
            checks.append(CashCheck(tyche, cash, accrued, allowed, CashOutcome.PRICED))
            continue
        for order in orders:
            differences.append(_unpriced(order, gap, several=len(orders) > 1))
        outcome = _outcome(gap, allowed)
        checks.append(CashCheck(tyche, cash, accrued, allowed, outcome))
        if outcome is CashOutcome.EXCEEDED:
            differences.append(
                Difference(
                    DifferenceKind.CASH,
                    str(currency),
                    f"Tyche has {tyche}, the broker {cash.total} plus {accrued} accrued "
                    f"dividends: a gap of {gap}, more than the {allowed} allowed",
                )
            )

    return Reconciliation(
        at=at,
        differences=tuple(differences),
        inferred=tuple(inferred),
        ended=tuple(ended),
        cash=tuple(checks),
    )


def _signed(working: WorkingOrder) -> Decimal:
    """The change in shares the order makes if all its remaining shares fill."""
    order = working.state.order
    remaining = working.state.remaining
    return remaining if order.side is Side.BUY else -remaining


def _ended(working: WorkingOrder) -> EndedOrder:
    order = working.state.order
    return EndedOrder(order.client_order_id, order.instrument, order.order_type)


def _position(
    instrument: Instrument, held: Decimal, reported: Decimal, gone: list[WorkingOrder]
) -> Difference:
    detail = f"Tyche holds {held}, the broker {reported}"
    if gone:
        ids = ", ".join(o.state.order.client_order_id for o in gone)
        detail += f"; orders the broker no longer lists do not explain it: {ids}"
    return Difference(DifferenceKind.POSITION, str(instrument), detail)


def _allowed(
    rules: ReconciliationRules,
    memory: ReconciliationState,
    account: Account,
    currency: Currency,
) -> Money:
    """The tolerance plus the dividends on their way (ADR-0044, decision 4).

    Dividends the broker reports accrued now are already on its side of the gap. Those
    Tyche credited since the last check may not be accrued yet, and those accrued then
    may be paid net of withholding.
    """
    credited = account.distributions_received(currency) - memory.distributions_in(currency)
    if credited.is_negative:
        credited = Money.zero(currency)
    return rules.tolerance(currency) + credited + memory.accrued_in(currency)


def _outcome(gap: Money, allowed: Money) -> CashOutcome:
    if gap.is_zero:
        return CashOutcome.MATCH
    if abs(gap) <= allowed:
        return CashOutcome.ADOPTED
    return CashOutcome.EXCEEDED


def _inferred(working: WorkingOrder, gap: Money) -> InferredFill | None:
    """The fill ``working`` made on a missed day, priced from the cash gap; or ``None``.

    A sale brought cash in, so the gap is its proceeds; a purchase took cash out, so
    the gap is minus its cost. Commission is folded into the price.
    """
    order = working.state.order
    quantity = working.state.remaining
    proceeds = gap if order.side is Side.SELL else -gap
    price = (proceeds / quantity).round_to(PRICE_PLACES)
    if not price.is_positive:
        return None
    return InferredFill(order.client_order_id, order.instrument, order.side, quantity, price)


def _unpriced(working: WorkingOrder, gap: Money, *, several: bool) -> Difference:
    order = working.state.order
    if several:
        why = f"several missed fills share one {gap.currency} cash gap, so none can be priced"
    else:
        why = f"the {gap.currency} cash gap of {gap} gives it no positive price"
    return Difference(
        DifferenceKind.POSITION,
        str(order.instrument),
        f"order {order.client_order_id} would explain the shares, but {why}",
    )

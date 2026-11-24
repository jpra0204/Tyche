"""Applying a reconciliation to Tyche's records: after each check, and on resume.

``correct`` runs after every check (ADR-0044, decisions 3, 4 and 6):

* a **mismatch** changes nothing but the halt: the checkpoint now holds the latest
  mismatch, which the risk gate reads, and which ``tyche resume`` will apply;
* a check that **agrees** (a match, or corrected) drops the orders that ended with no
  shares moved, takes the broker's cash where the gap was within what is allowed, and
  remembers the check. A halt already in place stays: only ``tyche resume`` lifts it.

``resolve`` is ``tyche resume``'s part (decision 7). If no check agreed after the halt,
it applies what the halt explained, in order: each inferred fill (to the account, the
sleeves it served and execution's working orders), then the broker's cash as the halt
recorded it, then the orders that ended. Then it lifts the halt.

Both return a new checkpoint with the same run id. It is dated no earlier than the
reconciliation, so the caller saves it under its own run id.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from tyche.core.domain import (
    Account,
    Checkpoint,
    ExecutionState,
    Fill,
    InferredFill,
    Instrument,
    Money,
    Reconciliation,
    ReconciliationState,
    ReconciliationStatus,
    Side,
    SleeveHolding,
    SleeveState,
    WorkingOrder,
)
from tyche.core.domain.account import COST_PLACES


class ReconciliationError(ValueError):
    """A reconciliation does not fit the checkpoint it is applied to: a bug."""


def correct(checkpoint: Checkpoint, reconciliation: Reconciliation) -> Checkpoint:
    """``checkpoint`` after ``reconciliation``: corrected, or halted.

    Raises:
        ReconciliationError: it names an order the checkpoint does not hold.
    """
    memory = checkpoint.reconciliation
    if reconciliation.status is ReconciliationStatus.MISMATCH:
        halted = replace(memory, halt=reconciliation)
        return _dated(checkpoint, reconciliation.at, reconciliation=halted)
    account = checkpoint.account
    for check in reconciliation.cash:
        account = account.with_cash(check.adopted)
    sleeves, execution = _drop_ended(checkpoint.sleeves, checkpoint.execution, reconciliation)
    return _dated(
        checkpoint,
        reconciliation.at,
        account=account,
        sleeves=sleeves,
        execution=execution,
        reconciliation=_remembered(reconciliation, account, halt=memory.halt),
    )


def resolve(checkpoint: Checkpoint, at: datetime) -> Checkpoint:
    """``checkpoint`` with the reconciliation halt lifted, as ``tyche resume`` does.

    Raises:
        ReconciliationError: there is no halt, or it does not fit the checkpoint.
    """
    memory = checkpoint.reconciliation
    halt = memory.halt
    if halt is None:
        raise ReconciliationError("no reconciliation halt to lift")
    if not memory.halt_is_current:
        return _dated(checkpoint, at, reconciliation=replace(memory, halt=None))
    account = checkpoint.account
    sleeves = checkpoint.sleeves
    execution = checkpoint.execution
    for fill in halt.inferred:
        account, sleeves, execution = _apply(fill, halt.at, account, sleeves, execution)
    for check in halt.cash:
        account = account.with_cash(check.adopted)
    sleeves, execution = _drop_ended(sleeves, execution, halt)
    return _dated(
        checkpoint,
        at,
        account=account,
        sleeves=sleeves,
        execution=execution,
        reconciliation=_remembered(halt, account, halt=None),
    )


def _dated(
    checkpoint: Checkpoint,
    at: datetime,
    *,
    reconciliation: ReconciliationState,
    account: Account | None = None,
    sleeves: SleeveState | None = None,
    execution: ExecutionState | None = None,
) -> Checkpoint:
    return replace(
        checkpoint,
        saved_at=max(checkpoint.saved_at, at),
        account=account if account is not None else checkpoint.account,
        sleeves=sleeves if sleeves is not None else checkpoint.sleeves,
        execution=execution if execution is not None else checkpoint.execution,
        reconciliation=reconciliation,
    )


def _remembered(
    reconciliation: Reconciliation, account: Account, *, halt: Reconciliation | None
) -> ReconciliationState:
    return ReconciliationState(
        last_at=reconciliation.at,
        distributions=tuple(
            account.distributions_received(c.currency) for c in reconciliation.cash
        ),
        accrued=tuple(c.accrued for c in reconciliation.cash),
        halt=halt,
    )


def _working(execution: ExecutionState, order_id: str) -> WorkingOrder:
    for working in execution.orders:
        if working.state.order.client_order_id == order_id:
            return working
    raise ReconciliationError(f"order {order_id} is not one of the checkpoint's working orders")


def _without(
    sleeves: SleeveState, execution: ExecutionState, order_id: str
) -> tuple[SleeveState, ExecutionState]:
    """Drop a working order, and the sleeve stop it was, from Tyche's records."""
    _working(execution, order_id)
    return (
        replace(sleeves, stops=tuple(s for s in sleeves.stops if s.client_order_id != order_id)),
        replace(
            execution,
            orders=tuple(o for o in execution.orders if o.state.order.client_order_id != order_id),
        ),
    )


def _drop_ended(
    sleeves: SleeveState, execution: ExecutionState, reconciliation: Reconciliation
) -> tuple[SleeveState, ExecutionState]:
    for ended in reconciliation.ended:
        sleeves, execution = _without(sleeves, execution, ended.client_order_id)
    return sleeves, execution


def _apply(
    inferred: InferredFill,
    at: datetime,
    account: Account,
    sleeves: SleeveState,
    execution: ExecutionState,
) -> tuple[Account, SleeveState, ExecutionState]:
    """One inferred fill applied to the account, the sleeves it served and the orders.

    The day it happened is unknown, so it is recorded on the day of the check.
    """
    working = _working(execution, inferred.client_order_id)
    order = working.state.order
    if (order.instrument, order.side, working.state.remaining) != (
        inferred.instrument,
        inferred.side,
        inferred.quantity,
    ):
        raise ReconciliationError(f"inferred fill of {inferred.client_order_id} does not fit it")
    moment = at.astimezone(UTC)
    day = moment.date()
    fill = Fill(
        fill_id=f"{inferred.client_order_id}-inferred",
        client_order_id=inferred.client_order_id,
        instrument=inferred.instrument,
        side=inferred.side,
        quantity=inferred.quantity,
        price=inferred.price,
        commission=Money.zero(inferred.price.currency),
        filled_at=moment,
        trade_date=day,
        settles_on=day,
    )
    account = account.apply_fill(fill)
    shares = (
        {working.strategy_id: inferred.quantity}
        if working.strategy_id is not None
        else {o.strategy_id: o.quantity for o in working.owed}
    )
    holdings: dict[tuple[str, Instrument], SleeveHolding | None] = {
        (h.strategy_id, h.instrument): h for h in sleeves.holdings
    }
    for strategy_id, quantity in sorted(shares.items()):
        key = (strategy_id, inferred.instrument)
        holdings[key] = _moved(holdings.get(key), strategy_id, inferred, quantity, day)
    kept = [h for h in holdings.values() if h is not None]
    kept.sort(key=lambda h: (h.strategy_id, *_key(h.instrument)))
    sleeves = replace(sleeves, holdings=tuple(kept))
    sleeves, execution = _without(sleeves, execution, inferred.client_order_id)
    return account, sleeves, execution


def _key(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, instrument.exchange


def _moved(
    held: SleeveHolding | None,
    strategy_id: str,
    fill: InferredFill,
    quantity: Decimal,
    day: date,
) -> SleeveHolding | None:
    """One sleeve's holding after its share of an inferred fill; ``None`` if emptied."""
    if fill.side is Side.BUY:
        if held is None:
            cost = fill.price * quantity
            return SleeveHolding(strategy_id, fill.instrument, quantity, cost, day)
        cost = held.cost + fill.price * quantity
        return replace(held, quantity=held.quantity + quantity, cost=cost)
    if held is None or held.quantity < quantity:
        have = held.quantity if held else 0
        raise ReconciliationError(
            f"the inferred sale of {fill.client_order_id} sells {quantity} {fill.instrument} "
            f"for {strategy_id}, which holds {have}"
        )
    left = held.quantity - quantity
    if left == 0:
        return None
    cost = (held.cost * left / held.quantity).round_to(COST_PLACES)
    return replace(held, quantity=left, cost=cost)

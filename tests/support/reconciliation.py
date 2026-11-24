"""Reconciliation in tests: the broker's side built from a checkpoint, and ready halts.

The checkpoint is the one in ``tests.support.checkpoints``: 10 SPY (alpha 6, beta 4), USD 5,299
of cash (10,000 settled, 4,701 still to pay), a market order buying 3 SPY for beta and
alpha's sell stop for 6 at 440, both working; here without its drawdown halt.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from tests.support import checkpoints
from tests.support.costs import usd
from tests.support.market import SPY
from tests.support.walks import NYSE
from tyche.core.domain import (
    Account,
    BrokerOrder,
    BrokerRecord,
    Checkpoint,
    Currency,
    Difference,
    DifferenceKind,
    Instrument,
    Money,
    Position,
    Reconciliation,
    ReconciliationRules,
)
from tyche.core.pipeline.reconciliation import correct, reconcile

RULES = ReconciliationRules(cash_tolerance=Decimal("1.00"))
CALENDARS = {"XNYS": NYSE}
USD = (Currency.USD,)
AT = datetime(2024, 1, 4, 0, 15, tzinfo=UTC)
"""When the checks are made: after the checkpoint was saved."""
STOP = "sim-000001-stop-alpha"
BUY = "20240103T210000Z-SPY.ARCX-buy"


def agreeing() -> Checkpoint:
    """The support checkpoint without its drawdown halt."""
    return replace(checkpoints.checkpoint(), rules=checkpoints.rules())


def broker_record(
    checkpoint: Checkpoint,
    *,
    shares: Mapping[Instrument, str] | None = None,
    cash: Money | None = None,
    without: Sequence[str] = (),
    orders: Mapping[str, str] | None = None,
    accrued: Sequence[Money] = (),
    foreign: int = 0,
    unresolved: Sequence[str] = (),
) -> BrokerRecord:
    """What the broker reports when it agrees with ``checkpoint``, but for what is given.

    Args:
        shares: Shares the broker holds of these instruments instead.
        cash: The broker's total USD cash instead, all settled.
        without: Orders the broker no longer lists.
        orders: More orders the broker lists, or other remaining shares, by id.
    """
    account = checkpoint.account
    held = {p.instrument: p for p in account.positions}
    for instrument, quantity in (shares or {}).items():
        if Decimal(quantity) == 0:
            held.pop(instrument, None)
        else:
            held[instrument] = Position(instrument, Decimal(quantity), usd("1") * Decimal(quantity))
    balance = account.cash(Currency.USD)
    reported = Account.reported(
        settled=(cash if cash is not None else balance.settled,),
        pending=() if cash is not None else balance.pending,
        positions=tuple(held.values()),
        marks={i: account.mark_of(i) or usd("100") for i in held},
    )
    listed = {
        o.state.order.client_order_id: o.state.remaining
        for o in checkpoint.execution.orders
        if o.state.order.client_order_id not in without
    }
    listed.update({k: Decimal(v) for k, v in (orders or {}).items()})
    return BrokerRecord(
        account=reported,
        orders=tuple(BrokerOrder(k, v) for k, v in sorted(listed.items())),
        foreign_orders=foreign,
        accrued_dividends=tuple(accrued),
        unresolved=tuple(unresolved),
    )


def mismatch(at: datetime) -> Reconciliation:
    """A mismatch with one unexplained position difference."""
    return Reconciliation(
        at=at,
        differences=(
            Difference(DifferenceKind.POSITION, "SPY.ARCX", "Tyche holds 10, the broker 4"),
        ),
    )


def unreconciled() -> Checkpoint:
    """Alpha's stop sold 6 SPY on a day no run read, and reconciliation halted."""
    mine = agreeing()
    theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))
    return replace(
        correct(mine, reconcile(mine, theirs, RULES, USD, AT, calendars=CALENDARS)),
        run_id="paper-halted",
    )

"""Trading events: execution's plan, orders, fills, the account and cash distributions.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime

from tyche.core.domain import Account, CashDistribution, Fill, OrderState, PlanLine
from tyche.core.domain.validation import require_utc
from tyche.core.events.event import Event


@dataclass(frozen=True, slots=True)
class ExecutionPlanEvent(Event):
    """What execution planned at one decision cycle, sleeve by sleeve (ADR-0023).

    Published by execution after it has handled an ``ApprovedPortfolioEvent`` and
    before the cycle's orders, so the journal can say why each sleeve traded what it
    did, or why it did not.

    Attributes:
        as_of: The decision time, copied from the ``ApprovedPortfolioEvent``.
        lines: One per sleeve and instrument the sleeve holds or targets, ordered by
            strategy id, then symbol and exchange.
    """

    as_of: datetime
    lines: tuple[PlanLine, ...]

    def __post_init__(self) -> None:
        require_utc(self.as_of, "ExecutionPlanEvent as_of")
        keys = [(p.strategy_id, p.instrument.symbol, p.instrument.exchange) for p in self.lines]
        if keys != sorted(set(keys)):
            raise ValueError(
                "ExecutionPlanEvent: lines must be one per sleeve and instrument, in order"
            )


@dataclass(frozen=True, slots=True)
class OrderEvent(Event):
    """An order changed status. One event per transition of its lifecycle.

    Execution publishes the ``SUBMITTED`` state; the broker publishes every status
    after that, with the reason in ``state.note`` when there is one.
    """

    state: OrderState


@dataclass(frozen=True, slots=True)
class FillEvent(Event):
    """Shares changed hands. Published by the broker, before the order's new status."""

    fill: Fill


@dataclass(frozen=True, slots=True)
class DistributionEvent(Event):
    """A cash distribution goes ex: holders at the previous close are owed the cash.

    Published by the feed at the open of the ex-date session, before that session's
    bars, so the broker sees who held the shares at the previous close.
    """

    distribution: CashDistribution


@dataclass(frozen=True, slots=True)
class CancelRequestEvent(Event):
    """Execution asked the broker to cancel an order (ADR-0023).

    A request, not a result: the broker publishes the order's ``CANCELLED`` status if
    the order was still open, and ignores the request if it had already finished (a
    stop that filled a moment earlier, say).

    Attributes:
        client_order_id: The order to cancel.
        reason: Why, in words, for the journal.
    """

    client_order_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("CancelRequestEvent: needs a client_order_id")
        if not self.reason.strip():
            raise ValueError(f"CancelRequestEvent for {self.client_order_id}: needs a reason")


@dataclass(frozen=True, slots=True)
class AccountEvent(Event):
    """Tyche's own view of the account at the close of a session.

    Published by account state once per session close, after that session's fills,
    settlement and marks, and so before the decision cycle that starts at the same
    close. Execution sizes orders from it; the risk layer (Phase 2) will measure the
    daily loss from one to the next (ADR-0015); reconciliation (Phase 2) compares it
    with the broker's own record.

    Attributes:
        as_of: The session's close, in UTC.
        account: The snapshot: cash per currency (settled and unsettled), positions at
            average cost, the closing marks, realised profit and distributions.
    """

    as_of: datetime
    account: Account

    def __post_init__(self) -> None:
        require_utc(self.as_of, "AccountEvent as_of")

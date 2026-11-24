"""A fake IB Gateway behind the ``IBClient`` protocol, for testing ``IBKRBroker``.

It keeps orders, executions and account values the way the gateway reports them, and
can lose the connection while an order is being sent: before it arrives, or after.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from tyche.adapters.brokers.ibkr import (
    ContractQuery,
    IBKRConnectionError,
    IBKRContractError,
    OrderTicket,
    ReportedExecution,
    ReportedHolding,
    ReportedOrder,
    ReportedValue,
)

ACCOUNT = "TEST-PAPER-1"
"""A made-up account id. Never a real one in the repository."""

DONE = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})


class Drop(Enum):
    """Where the connection is lost while the next order is sent."""

    BEFORE_ARRIVAL = "before"
    AFTER_ARRIVAL = "after"


@dataclass
class FakeGateway:
    """Implements ``IBClient``. Tests drive it directly: statuses, executions, values."""

    accounts: tuple[str, ...] = (ACCOUNT,)
    contracts: dict[str, list[tuple[int, str]]] = field(
        default_factory=lambda: {"SPY": [(756733, "ARCA")], "QQQ": [(320227571, "NASDAQ")]}
    )
    connected: bool = False
    refuse_connection: bool = False
    drop: Drop | None = None
    connects: list[tuple[str, int, int, float]] = field(default_factory=list)
    lookups: list[ContractQuery] = field(default_factory=list)
    placed: list[OrderTicket] = field(default_factory=list)
    cancelled: list[int] = field(default_factory=list)
    orders: dict[int, ReportedOrder] = field(default_factory=dict)
    execs: list[ReportedExecution] = field(default_factory=list)
    values: list[ReportedValue] = field(default_factory=list)
    portfolio: list[ReportedHolding] = field(default_factory=list)
    on_place: list[Callable[[OrderTicket], None]] = field(default_factory=list)
    next_id: int = 101
    next_perm: int = 900001

    # --- IBClient ---------------------------------------------------------------------

    def connect(self, host: str, port: int, client_id: int, timeout: float) -> None:
        self.connects.append((host, port, client_id, timeout))
        if self.refuse_connection:
            raise IBKRConnectionError(f"cannot connect to IB Gateway at {host}:{port}")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def managed_accounts(self) -> tuple[str, ...]:
        return self.accounts

    def contract_id(self, query: ContractQuery) -> int:
        self._require()
        self.lookups.append(query)
        found = [
            con_id
            for con_id, primary in self.contracts.get(query.symbol, [])
            if query.primary_exchange in (None, primary)
        ]
        if len(found) != 1:
            raise IBKRContractError(f"{len(found)} stocks {query.symbol} match")
        return found[0]

    def place(self, ticket: OrderTicket) -> int:
        self._require()
        for hook in self.on_place:
            hook(ticket)
        if self.drop is Drop.BEFORE_ARRIVAL:
            self.drop, self.connected = None, False
            raise IBKRConnectionError("lost before the order arrived")
        order_id = self.next_id
        self.next_id += 1
        self.placed.append(ticket)
        self.orders[order_id] = ReportedOrder(
            order_ref=ticket.order_ref,
            order_id=order_id,
            perm_id=self.next_perm,
            account=ticket.account,
            status="PreSubmitted",
            filled=Decimal(0),
            remaining=Decimal(ticket.quantity),
        )
        self.next_perm += 1
        if self.drop is Drop.AFTER_ARRIVAL:
            self.drop, self.connected = None, False
            raise IBKRConnectionError("lost after the order arrived")
        return order_id

    def cancel(self, order_id: int) -> None:
        self._require()
        self.cancelled.append(order_id)

    def open_orders(self) -> tuple[ReportedOrder, ...]:
        self._require()
        return tuple(o for o in self.orders.values() if o.status not in DONE)

    def completed_orders(self) -> tuple[ReportedOrder, ...]:
        self._require()
        return tuple(o for o in self.orders.values() if o.status in DONE)

    def executions(self, account: str) -> tuple[ReportedExecution, ...]:
        self._require()
        return tuple(e for e in self.execs if e.account == account)

    def holdings(self, account: str) -> tuple[ReportedHolding, ...]:
        self._require()
        return tuple(h for h in self.portfolio if h.account == account)

    def account_values(self, account: str) -> tuple[ReportedValue, ...]:
        self._require()
        return tuple(v for v in self.values if v.account == account)

    # --- what a test does to the gateway ------------------------------------------------

    def order_for(self, order_ref: str) -> ReportedOrder:
        return next(o for o in self.orders.values() if o.order_ref == order_ref)

    def set_status(self, order_ref: str, status: str, message: str = "") -> None:
        order = self.order_for(order_ref)
        self.orders[order.order_id] = replace(order, status=status, message=message)

    def forget(self, order_ref: str) -> None:
        """IBKR no longer lists the order (an earlier day's, or cancelled by IBKR)."""
        del self.orders[self.order_for(order_ref).order_id]

    def execute(
        self,
        order_ref: str,
        shares: str,
        price: str,
        at: datetime,
        *,
        exec_id: str | None = None,
        commission: str | None = "1.00",
        currency: str = "USD",
        side: str | None = None,
    ) -> ReportedExecution:
        order = self.order_for(order_ref)
        ticket = next(t for t in self.placed if t.order_ref == order_ref)
        execution = ReportedExecution(
            exec_id=exec_id or f"0000e0d5.{len(self.execs) + 1:08x}.01.01",
            order_ref=order_ref,
            order_id=order.order_id,
            perm_id=order.perm_id,
            account=order.account,
            side=side or ("BOT" if ticket.action == "BUY" else "SLD"),
            shares=Decimal(shares),
            price=Decimal(price),
            time=at,
            commission=None if commission is None else Decimal(commission),
            commission_currency=None if commission is None else currency,
        )
        self.execs.append(execution)
        return execution

    def report_commission(self, exec_id: str, commission: str, currency: str = "USD") -> None:
        index = next(i for i, e in enumerate(self.execs) if e.exec_id == exec_id)
        self.execs[index] = replace(
            self.execs[index], commission=Decimal(commission), commission_currency=currency
        )

    def _require(self) -> None:
        if not self.connected:
            raise IBKRConnectionError("not connected")

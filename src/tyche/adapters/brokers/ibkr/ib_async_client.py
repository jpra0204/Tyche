"""IbAsyncClient: the ``IBClient`` protocol on ``ib_async`` and a running IB Gateway.

Translation only: every rule lives in ``IBKRBroker``, which is tested against a fake.
The translation functions below are pure, so they are tested on ``ib_async``'s own
objects without a gateway; the network calls are covered by the opt-in tests marked
``ibkr_paper`` (paper account only).

``ib_async`` 2.1.0, BSD 2-Clause (ADR-0041). Its blocking methods run its own event
loop until the gateway answers.
"""

from collections.abc import Callable
from decimal import Decimal

from ib_async import (
    IB,
    AccountValue,
    Contract,
    ExecutionFilter,
    Order,
    PortfolioItem,
    Stock,
    Trade,
)
from ib_async import Fill as IbFill

from tyche.adapters.brokers.ibkr.client import (
    ContractQuery,
    IBKRConnectionError,
    IBKRContractError,
    OrderTicket,
    ReportedExecution,
    ReportedHolding,
    ReportedOrder,
    ReportedValue,
)


class IbAsyncClient:
    """Implements ``IBClient`` with ``ib_async``.

    Args:
        ib: The ``ib_async`` session; a new one by default.
    """

    def __init__(self, ib: IB | None = None) -> None:
        self._ib = ib if ib is not None else IB()

    def connect(self, host: str, port: int, client_id: int, timeout: float) -> None:
        try:
            self._ib.connect(host, port, clientId=client_id, timeout=timeout, raiseSyncErrors=True)
        except (ConnectionError, OSError, TimeoutError) as error:
            raise IBKRConnectionError(
                f"cannot connect to IB Gateway at {host}:{port}: {type(error).__name__}"
            ) from error

    def disconnect(self) -> None:
        self._ib.disconnect()

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def managed_accounts(self) -> tuple[str, ...]:
        return tuple(self._ib.managedAccounts())

    def contract_id(self, query: ContractQuery) -> int:
        self._require()
        contract = Stock(
            query.symbol, "SMART", query.currency, primaryExchange=query.primary_exchange or ""
        )
        details = self._call(lambda: self._ib.reqContractDetails(contract))
        found = [d.contract for d in details if d.contract is not None and d.contract.conId]
        return contract_id_from(query, [(c.conId, c.secType, c.primaryExchange) for c in found])

    def place(self, ticket: OrderTicket) -> int:
        self._require()
        contract, order = ib_order(ticket)
        trade = self._call(lambda: self._ib.placeOrder(contract, order))
        return int(trade.order.orderId)

    def cancel(self, order_id: int) -> None:
        self._require()
        known = [t.order for t in self._ib.trades() if t.order.orderId == order_id]
        order = known[0] if known else Order(orderId=order_id)
        self._call(lambda: self._ib.cancelOrder(order))

    def open_orders(self) -> tuple[ReportedOrder, ...]:
        self._require()
        return tuple(reported_order(t) for t in self._call(self._ib.reqOpenOrders))

    def completed_orders(self) -> tuple[ReportedOrder, ...]:
        self._require()
        trades = self._call(lambda: self._ib.reqCompletedOrders(apiOnly=True))
        return tuple(reported_order(t) for t in trades)

    def executions(self, account: str) -> tuple[ReportedExecution, ...]:
        self._require()
        self._call(lambda: self._ib.reqExecutions(ExecutionFilter(acctCode=account)))
        # The session's own list also holds commission reports that arrived after
        # the request ended.
        return tuple(
            reported_execution(f) for f in self._ib.fills() if f.execution.acctNumber == account
        )

    def holdings(self, account: str) -> tuple[ReportedHolding, ...]:
        self._require()
        return tuple(reported_holding(item) for item in self._ib.portfolio(account))

    def account_values(self, account: str) -> tuple[ReportedValue, ...]:
        self._require()
        return tuple(reported_value(v) for v in self._ib.accountValues(account))

    def _require(self) -> None:
        if not self._ib.isConnected():
            raise IBKRConnectionError("not connected to IB Gateway")

    def _call[T](self, request: Callable[[], T]) -> T:
        try:
            return request()
        except (ConnectionError, OSError, TimeoutError) as error:
            raise IBKRConnectionError(
                f"the connection to IB Gateway failed: {type(error).__name__}"
            ) from error


# --- translation, pure ------------------------------------------------------------


def contract_id_from(query: ContractQuery, found: list[tuple[int, str, str]]) -> int:
    """The one stock contract among ``(conId, secType, primaryExchange)`` matches.

    Raises:
        IBKRContractError: none or several match.
    """
    stocks = sorted({(con_id, primary) for con_id, sec_type, primary in found if sec_type == "STK"})
    where = f" on {query.primary_exchange}" if query.primary_exchange else ""
    if not stocks:
        raise IBKRContractError(f"IBKR knows no stock {query.symbol} in {query.currency}{where}")
    if len(stocks) > 1:
        listings = ", ".join(f"{primary or '?'} ({con_id})" for con_id, primary in stocks)
        raise IBKRContractError(
            f"IBKR has {len(stocks)} stocks {query.symbol} in {query.currency}{where}: "
            f"{listings}; Tyche needs IBKR's code for the listing exchange to choose"
        )
    return stocks[0][0]


def ib_order(ticket: OrderTicket) -> tuple[Contract, Order]:
    """The ``ib_async`` contract and order for ``ticket`` (ADR-0041)."""
    contract = Contract(conId=ticket.contract_id, exchange="SMART")
    order = Order(
        action=ticket.action,
        totalQuantity=ticket.quantity,
        orderType=ticket.order_type,
        tif=ticket.time_in_force,
        orderRef=ticket.order_ref,
        account=ticket.account,
        outsideRth=False,
        transmit=True,
    )
    if ticket.stop_price is not None:
        order.auxPrice = float(ticket.stop_price)
    return contract, order


def reported_order(trade: Trade) -> ReportedOrder:
    """An ``ib_async`` trade as a ``ReportedOrder``."""
    messages = [entry for entry in trade.log if entry.message]
    message = ""
    if messages:
        last = messages[-1]
        message = f"{last.errorCode} {last.message}" if last.errorCode else last.message
    status = trade.orderStatus
    return ReportedOrder(
        order_ref=trade.order.orderRef or "",
        order_id=int(trade.order.orderId),
        perm_id=int(trade.order.permId or status.permId or 0),
        account=trade.order.account or "",
        status=status.status,
        filled=_decimal(status.filled),
        remaining=_decimal(status.remaining),
        message=message,
    )


def reported_execution(fill: IbFill) -> ReportedExecution:
    """An ``ib_async`` fill as a ``ReportedExecution``; no commission until it is reported."""
    execution = fill.execution
    report = fill.commissionReport
    known = bool(report.execId) and report.execId == execution.execId
    return ReportedExecution(
        exec_id=execution.execId,
        order_ref=execution.orderRef or "",
        order_id=int(execution.orderId),
        perm_id=int(execution.permId),
        account=execution.acctNumber,
        side=execution.side,
        shares=_decimal(execution.shares),
        price=_decimal(execution.price),
        time=execution.time,
        commission=_decimal(report.commission) if known else None,
        commission_currency=report.currency if known else None,
    )


def reported_holding(item: PortfolioItem) -> ReportedHolding:
    """An ``ib_async`` portfolio item as a ``ReportedHolding``."""
    return ReportedHolding(
        account=item.account,
        symbol=item.contract.symbol,
        currency=item.contract.currency,
        quantity=_decimal(item.position),
        average_cost=_decimal(item.averageCost),
        market_price=_decimal(item.marketPrice),
    )


def reported_value(value: AccountValue) -> ReportedValue:
    """An ``ib_async`` account value as a ``ReportedValue``."""
    return ReportedValue(
        account=value.account, tag=value.tag, value=value.value, currency=value.currency
    )


def _decimal(value: float | Decimal) -> Decimal:
    """A number from ``ib_async`` as an exact decimal: the shortest text that round-trips."""
    return value if isinstance(value, Decimal) else Decimal(repr(float(value)))

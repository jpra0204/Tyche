"""The ib_async translation, on ib_async's own objects, with no gateway."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ib_async import (
    AccountValue,
    CommissionReport,
    Contract,
    Execution,
    OrderStatus,
    PortfolioItem,
    Stock,
    Trade,
    TradeLogEntry,
)
from ib_async import Fill as IbFill
from ib_async import Order as IbOrder

from tyche.adapters.brokers.ibkr import (
    ContractQuery,
    IbAsyncClient,
    IBKRConnectionError,
    IBKRContractError,
    OrderTicket,
)
from tyche.adapters.brokers.ibkr.ib_async_client import (
    contract_id_from,
    ib_order,
    reported_execution,
    reported_holding,
    reported_order,
    reported_value,
)

WHEN = datetime(2024, 1, 3, 14, 30, tzinfo=UTC)
SPY = ContractQuery("SPY", "USD", "ARCA")


def test_a_market_on_open_ticket() -> None:
    contract, order = ib_order(OrderTicket("o-1", "TEST-PAPER-1", 756733, "BUY", 12, "MKT", "OPG"))
    assert (contract.conId, contract.exchange) == (756733, "SMART")
    assert (order.action, order.totalQuantity, order.orderType, order.tif) == (
        "BUY",
        12,
        "MKT",
        "OPG",
    )
    assert (order.orderRef, order.account) == ("o-1", "TEST-PAPER-1")
    assert order.outsideRth is False
    assert order.transmit is True


def test_a_stop_ticket_carries_its_price() -> None:
    _, order = ib_order(
        OrderTicket("o-2", "A", 1, "SELL", 5, "STP", "GTC", stop_price=Decimal("451.37"))
    )
    assert (order.orderType, order.tif, order.auxPrice) == ("STP", "GTC", 451.37)


def test_one_stock_contract_is_chosen() -> None:
    found = [(756733, "STK", "ARCA"), (99, "OPT", "ARCA")]
    assert contract_id_from(SPY, found) == 756733


def test_no_stock_contract_is_an_error() -> None:
    with pytest.raises(IBKRContractError, match="knows no stock SPY in USD on ARCA"):
        contract_id_from(SPY, [(99, "OPT", "ARCA")])


def test_several_stock_contracts_name_their_listings() -> None:
    query = ContractQuery("ABC", "USD", None)
    with pytest.raises(IBKRContractError, match=r"2 stocks ABC in USD: NYSE \(1\), NASDAQ \(2\)"):
        contract_id_from(query, [(1, "STK", "NYSE"), (2, "STK", "NASDAQ")])


def test_an_order_as_ibkr_lists_it() -> None:
    trade = Trade(
        contract=Stock("SPY", "SMART", "USD"),
        order=IbOrder(orderId=101, permId=900001, orderRef="o-1", account="A"),
        orderStatus=OrderStatus(orderId=101, status="Cancelled", filled=3.0, remaining=7.0),
        log=[
            TradeLogEntry(WHEN, "PreSubmitted", ""),
            TradeLogEntry(WHEN, "Cancelled", "Order Canceled - reason:", 202),
        ],
    )
    reported = reported_order(trade)
    assert reported.order_ref == "o-1"
    assert (reported.order_id, reported.perm_id, reported.account) == (101, 900001, "A")
    assert (reported.status, reported.filled, reported.remaining) == (
        "Cancelled",
        Decimal(3),
        Decimal(7),
    )
    assert reported.message == "202 Order Canceled - reason:"


def test_an_order_with_no_message_and_its_perm_id_only_in_the_status() -> None:
    trade = Trade(
        order=IbOrder(orderId=5),
        orderStatus=OrderStatus(orderId=5, status="Submitted", permId=42),
        log=[TradeLogEntry(WHEN, "Submitted", "Note", 0)],
    )
    reported = reported_order(trade)
    assert (reported.order_ref, reported.perm_id, reported.message) == ("", 42, "Note")


def _fill(report: CommissionReport) -> IbFill:
    execution = Execution(
        execId="0000e0d5.01",
        time=WHEN,
        acctNumber="A",
        side="BOT",
        shares=10.0,
        price=470.12,
        permId=900001,
        orderId=101,
        orderRef="o-1",
    )
    return IbFill(Stock("SPY", "SMART", "USD"), execution, report, WHEN)


def test_an_execution_with_its_commission_report() -> None:
    reported = reported_execution(_fill(CommissionReport("0000e0d5.01", 1.0035, "USD")))
    assert (reported.exec_id, reported.order_ref, reported.order_id, reported.perm_id) == (
        "0000e0d5.01",
        "o-1",
        101,
        900001,
    )
    assert (reported.side, reported.shares, reported.price) == (
        "BOT",
        Decimal(10),
        Decimal("470.12"),
    )
    assert reported.time == WHEN
    assert (reported.commission, reported.commission_currency) == (Decimal("1.0035"), "USD")


def test_an_execution_before_its_commission_report() -> None:
    reported = reported_execution(_fill(CommissionReport()))
    assert (reported.commission, reported.commission_currency) == (None, None)


def test_a_holding_and_an_account_value() -> None:
    item = PortfolioItem(Stock("SPY", "SMART", "USD"), 10.0, 472.5, 4725.0, 470.2, 23.0, 0.0, "A")
    holding = reported_holding(item)
    assert (holding.account, holding.symbol, holding.currency) == ("A", "SPY", "USD")
    assert (holding.quantity, holding.average_cost, holding.market_price) == (
        Decimal(10),
        Decimal("470.2"),
        Decimal("472.5"),
    )
    value = reported_value(AccountValue("A", "SettledCashByDate", "20240103:1", "USD", ""))
    assert (value.account, value.tag, value.value, value.currency) == (
        "A",
        "SettledCashByDate",
        "20240103:1",
        "USD",
    )


def test_a_client_that_is_not_connected_refuses_every_request() -> None:
    client = IbAsyncClient()
    assert not client.is_connected()
    assert client.managed_accounts() == ()
    calls: list[Callable[[], object]] = [
        lambda: client.contract_id(SPY),
        lambda: client.place(OrderTicket("o", "A", 1, "BUY", 1, "MKT", "OPG")),
        lambda: client.cancel(1),
        client.open_orders,
        client.completed_orders,
        lambda: client.executions("A"),
        lambda: client.holdings("A"),
        lambda: client.account_values("A"),
    ]
    for call in calls:
        with pytest.raises(IBKRConnectionError):
            call()
    client.disconnect()  # harmless when not connected


def test_a_contract_id_from_ib_async_contracts() -> None:
    contract = Contract(conId=756733, secType="STK", primaryExchange="ARCA")
    assert contract_id_from(SPY, [(contract.conId, contract.secType, contract.primaryExchange)])

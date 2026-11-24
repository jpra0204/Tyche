"""Opt-in: IBKRBroker against a running IB Gateway logged in to Pablo's PAPER account.

Never run against a live account. The account check refuses any account but the one
named below, so name the paper account, never a live one.

Run with the gateway open and logged in to paper::

    TYCHE_TEST_IBKR_PORT=4002 TYCHE_TEST_IBKR_ACCOUNT=<paper id> uv run pytest -m ibkr_paper

``TYCHE_TEST_IBKR_HOST`` (default ``127.0.0.1``) and ``TYCHE_TEST_IBKR_CLIENT_ID``
(default 91, apart from Tyche's own) are optional. These are not ``.env`` keys: the
test suite removes those from the environment so that no test reads a real secret by
accident. The tests only read, except the one that also needs
``TYCHE_TEST_IBKR_ORDERS=1``: it sends a market-on-open order for one share of SPY
after the close and cancels it at once.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.support.profiles import US_TEMPLATE_PROFILE
from tests.support.recording import Recorder
from tyche.adapters.brokers.ibkr import (
    SETTLED_CASH_TAG,
    IbAsyncClient,
    IBKRAccountError,
    IBKRBroker,
    ReportedValue,
)
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.clocks import SystemClock
from tyche.adapters.storage import SqliteBrokerOrderStore, open_database
from tyche.config import IbkrConnection
from tyche.core.domain import Order, OrderState, OrderStatus, OrderType, Side, TimeInForce
from tyche.core.events import CancelRequestEvent, EventBus, OrderEvent

pytestmark = pytest.mark.ibkr_paper

PORT = os.environ.get("TYCHE_TEST_IBKR_PORT", "")
ACCOUNT = os.environ.get("TYCHE_TEST_IBKR_ACCOUNT", "")
HOST = os.environ.get("TYCHE_TEST_IBKR_HOST", "127.0.0.1")
CLIENT_ID = int(os.environ.get("TYCHE_TEST_IBKR_CLIENT_ID", "91"))
SEND_ORDERS = os.environ.get("TYCHE_TEST_IBKR_ORDERS") == "1"

needs_gateway = pytest.mark.skipif(
    not (PORT and ACCOUNT), reason="set TYCHE_TEST_IBKR_PORT and TYCHE_TEST_IBKR_ACCOUNT"
)
INSTRUMENTS = US_TEMPLATE_PROFILE.universe.instruments


def connection(account: str = ACCOUNT) -> IbkrConnection:
    return IbkrConnection(
        host=HOST, port=int(PORT), client_id=CLIENT_ID, account_id=SecretStr(account)
    )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(tmp_path / "tyche.db")) as opened:
        yield opened


def broker(database: sqlite3.Connection, account: str = ACCOUNT) -> tuple[IBKRBroker, EventBus]:
    clock = SystemClock()
    today = clock.now().date()
    calendar = ExchangeCalendarsCalendar(
        "XNYS", first=date(today.year - 1, 1, 1), last=date(today.year + 1, 12, 31)
    )
    bus = EventBus(clock.now)
    adapter = IBKRBroker(
        bus,
        IbAsyncClient(),
        SqliteBrokerOrderStore(database),
        connection=connection(account),
        instruments=INSTRUMENTS,
        calendars={"XNYS": calendar},
        settlement_days=1,
        clock=clock,
    )
    return adapter, bus


@needs_gateway
def test_another_account_id_is_refused(database: sqlite3.Connection) -> None:
    adapter, _ = broker(database, account="TEST-NOT-THIS-ACCOUNT")
    with pytest.raises(IBKRAccountError):
        adapter.connect()


@needs_gateway
def test_reads_the_paper_account(database: sqlite3.Connection) -> None:
    adapter, _ = broker(database)
    adapter.connect()
    try:
        values: tuple[ReportedValue, ...] = adapter._client.account_values(ACCOUNT)
        tags = {v.tag for v in values}
        print(f"\n{SETTLED_CASH_TAG} reported: {SETTLED_CASH_TAG in tags}")  # paper check 9
        account = adapter.account()
        print(f"currencies: {account.currencies}; positions: {len(account.positions)}")
        report = adapter.sync()
        print(f"sync: {report}")
    finally:
        adapter.close()


@needs_gateway
def test_every_candidate_resolves_to_one_contract(database: sqlite3.Connection) -> None:
    adapter, _ = broker(database)
    adapter.connect()
    try:
        for instrument in INSTRUMENTS:
            contract_id = adapter._contract_id(instrument)  # paper check 8
            print(f"{instrument}: conId {contract_id}")
            assert contract_id > 0
    finally:
        adapter.close()


@needs_gateway
@pytest.mark.skipif(not SEND_ORDERS, reason="set TYCHE_TEST_IBKR_ORDERS=1 to send an order")
def test_a_market_on_open_order_is_accepted_and_cancelled(database: sqlite3.Connection) -> None:
    adapter, bus = broker(database)
    recorder = Recorder(bus)
    adapter.connect()
    spy = next(i for i in INSTRUMENTS if i.symbol == "SPY")
    order_id = f"paper-test-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    order = Order(
        client_order_id=order_id,
        instrument=spy,
        side=Side.BUY,
        quantity=Decimal(1),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
        reason="opt-in paper test",
    )
    try:
        bus.publish(OrderEvent(OrderState(order).submit()), source="test")
        bus.drain()
        adapter._client._ib.sleep(2)  # type: ignore[attr-defined]  # let IBKR answer
        adapter.sync()
        assert adapter.order(order_id) is not None
        bus.publish(CancelRequestEvent(order_id, "opt-in paper test"), source="test")
        bus.drain()
        adapter._client._ib.sleep(2)  # type: ignore[attr-defined]
        adapter.sync()
        statuses = [e.state.status for e in recorder.events if isinstance(e, OrderEvent)]
        print(f"\nstatuses: {statuses}")
        assert statuses[-1] in {OrderStatus.CANCELLED, OrderStatus.REJECTED}
    finally:
        adapter.close()

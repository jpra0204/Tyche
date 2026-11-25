"""IBKRBroker against a fake gateway: identity, sending, never resending, reading back."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.adapters.brokers.ibkr.fake_gateway import ACCOUNT, Drop, FakeGateway
from tests.support.market import QQQ, SPY
from tests.support.recording import Recorder, TickingClock
from tyche.adapters.brokers.ibkr import (
    IBKRAccountError,
    IBKRBroker,
    IBKRBrokerError,
    IBKRConnectionError,
    IBKRError,
    OpenOrderStyle,
    ReportedHolding,
    ReportedOrder,
    ReportedValue,
    Unaccounted,
)
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.storage import Fate, SqliteBrokerOrderStore, open_database
from tyche.config import IbkrConnection
from tyche.core.domain import (
    AssetClass,
    BrokerOrder,
    Currency,
    Instrument,
    Money,
    Order,
    OrderState,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
)
from tyche.core.events import (
    CancelRequestEvent,
    Envelope,
    EventBus,
    FillEvent,
    HandlerError,
    OrderEvent,
)

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
DECIDED = datetime(2024, 1, 2, 21, 30, tzinfo=UTC)
OPEN_WED = datetime(2024, 1, 3, 14, 30, tzinfo=UTC)
NOON_WED = datetime(2024, 1, 3, 17, 0, tzinfo=UTC)
CONNECTION = IbkrConnection(host="127.0.0.1", port=4002, client_id=7, account_id=SecretStr(ACCOUNT))


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def market(order_id: str = "o-buy", side: Side = Side.BUY, quantity: str = "10") -> Order:
    return _order(order_id, side, quantity, OrderType.MARKET, TimeInForce.DAY)


def stop(order_id: str = "o-stop", price: str = "450.00", quantity: str = "10") -> Order:
    return _order(order_id, Side.SELL, quantity, OrderType.STOP, TimeInForce.GTC, price)


def _order(
    order_id: str,
    side: Side,
    quantity: str,
    order_type: OrderType,
    tif: TimeInForce,
    price: str | None = None,
    instrument: Instrument = SPY,
) -> Order:
    return Order(
        client_order_id=order_id,
        instrument=instrument,
        side=side,
        quantity=Decimal(quantity),
        order_type=order_type,
        time_in_force=tif,
        created_at=DECIDED,
        reason="test",
        stop_price=usd(price) if price else None,
    )


class Paper:
    """A bus, a fake gateway and an IBKRBroker on one state database."""

    def __init__(self, connection: sqlite3.Connection, gateway: FakeGateway | None = None) -> None:
        self.clock = TickingClock(DECIDED)
        self.bus = EventBus(self.clock.now)
        self.recorder = Recorder(self.bus)
        self.gateway = gateway or FakeGateway()
        self.store = SqliteBrokerOrderStore(connection)
        self.broker = IBKRBroker(
            self.bus,
            self.gateway,
            self.store,
            connection=CONNECTION,
            instruments=[SPY, QQQ],
            calendars={"XNYS": NYSE},
            settlement_days=1,
            clock=self.clock,
        )

    def submit(self, order: Order, *, release: bool = True) -> None:
        """Publish ``order`` as execution would; then, as the paper cycle does after a
        drain, send the sales held back (ADR-0045)."""
        self.bus.publish(OrderEvent(OrderState(order).submit()), source="execution")
        self.bus.drain()
        if release and self.broker.connected:
            self.broker.release()

    def cancel(self, order_id: str) -> None:
        self.bus.publish(CancelRequestEvent(order_id, "test"), source="execution")
        self.bus.drain()

    def states(self, order_id: str) -> list[OrderStatus]:
        return [
            e.state.status
            for e in self.recorder.events
            if isinstance(e, OrderEvent) and e.state.order.client_order_id == order_id
        ]

    def last(self, order_id: str) -> OrderState:
        return [
            e.state
            for e in self.recorder.events
            if isinstance(e, OrderEvent) and e.state.order.client_order_id == order_id
        ][-1]

    @property
    def fills(self) -> list[FillEvent]:
        return [e for e in self.recorder.events if isinstance(e, FillEvent)]


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(tmp_path / "state" / "tyche.db")) as connection:
        yield connection


@pytest.fixture
def paper(database: sqlite3.Connection) -> Paper:
    p = Paper(database)
    p.broker.connect()
    return p


# --- identity -----------------------------------------------------------------------


def test_connects_to_the_configured_account_with_the_configured_settings(
    database: sqlite3.Connection,
) -> None:
    p = Paper(database)
    p.broker.connect()
    assert p.broker.connected
    assert p.gateway.connects == [("127.0.0.1", 4002, 7, 10.0)]


@pytest.mark.parametrize(
    "accounts",
    [("TEST-LIVE-9",), (ACCOUNT, "TEST-LIVE-9"), (), (ACCOUNT.lower(),)],
    ids=["another", "one-more", "none", "different-case"],
)
def test_refuses_any_gateway_not_logged_in_to_exactly_the_configured_account(
    database: sqlite3.Connection, accounts: tuple[str, ...]
) -> None:
    p = Paper(database, FakeGateway(accounts=accounts))
    with pytest.raises(IBKRAccountError) as raised:
        p.broker.connect()
    assert not p.broker.connected
    assert not p.gateway.connected  # disconnected again
    assert ACCOUNT not in str(raised.value)
    assert "TEST-LIVE-9" not in str(raised.value)


def test_nothing_is_sent_before_the_account_is_checked(database: sqlite3.Connection) -> None:
    p = Paper(database)
    p.gateway.connected = True  # connected, but never through connect()
    p.submit(market())
    assert p.states("o-buy") == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert "no connection" in p.last("o-buy").note
    assert p.gateway.placed == []


def test_a_gateway_that_cannot_be_reached_says_so(database: sqlite3.Connection) -> None:
    p = Paper(database, FakeGateway(refuse_connection=True))
    with pytest.raises(IBKRConnectionError):
        p.broker.connect()
    assert not p.broker.connected


def test_client_id_zero_is_refused(database: sqlite3.Connection) -> None:
    zero = IbkrConnection(host="h", port=4002, client_id=0, account_id=SecretStr(ACCOUNT))
    with pytest.raises(IBKRError, match="client id 0"):
        IBKRBroker(
            EventBus(TickingClock().now),
            FakeGateway(),
            SqliteBrokerOrderStore(database),
            connection=zero,
            instruments=[SPY],
            calendars={"XNYS": NYSE},
            settlement_days=1,
            clock=TickingClock(),
        )


def test_close_disconnects(paper: Paper) -> None:
    paper.broker.close()
    assert not paper.broker.connected
    assert not paper.gateway.connected


# --- sending ------------------------------------------------------------------------


def test_a_market_order_goes_as_market_on_open_with_tyches_id(paper: Paper) -> None:
    paper.submit(market(quantity="12"))
    (ticket,) = paper.gateway.placed
    assert ticket.order_ref == "o-buy"
    assert ticket.account == ACCOUNT
    assert ticket.contract_id == 756733
    assert (ticket.action, ticket.quantity) == ("BUY", 12)
    assert (ticket.order_type, ticket.time_in_force, ticket.stop_price) == ("MKT", "OPG", None)
    # Only IBKR's answer moves it on: nothing is accepted yet.
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED]


def test_day_market_orders_are_the_fallback(database: sqlite3.Connection) -> None:
    p = Paper(database)
    p.broker = IBKRBroker(
        EventBus(p.clock.now),
        p.gateway,
        p.store,
        connection=CONNECTION,
        instruments=[SPY],
        calendars={"XNYS": NYSE},
        settlement_days=1,
        clock=p.clock,
        open_orders=OpenOrderStyle.DAY,
    )
    p.broker.connect()
    p.broker._on_order(_envelope(market()))
    assert p.gateway.placed[0].time_in_force == "DAY"


def _envelope(order: Order) -> Envelope[OrderEvent]:
    bus = EventBus(TickingClock().now)
    return bus.publish(OrderEvent(OrderState(order).submit()), source="test")  # type: ignore[return-value]


def test_a_stop_goes_good_till_cancelled_at_its_price(paper: Paper) -> None:
    paper.submit(stop(price="451.37"))
    (ticket,) = paper.gateway.placed
    assert (ticket.action, ticket.order_type, ticket.time_in_force) == ("SELL", "STP", "GTC")
    assert ticket.stop_price == Decimal("451.37")


def test_the_order_is_recorded_before_it_is_sent(paper: Paper) -> None:
    seen: list[Fate | None] = []

    def check(_: object) -> None:
        record = paper.store.get("o-buy")
        seen.append(record.fate if record else None)

    paper.gateway.on_place.append(check)
    paper.submit(market())
    assert seen == [Fate.SENDING]
    record = paper.store.get("o-buy")
    assert record is not None
    assert (record.fate, record.order_id) == (Fate.PLACED, 101)


def test_the_same_order_id_is_never_sent_twice(paper: Paper) -> None:
    paper.submit(market())
    paper.submit(market())
    assert len(paper.gateway.placed) == 1
    assert paper.broker.ignored_duplicates == ("o-buy",)


def test_an_order_id_sent_by_an_earlier_run_is_not_sent_again(
    database: sqlite3.Connection,
) -> None:
    first = Paper(database)
    first.broker.connect()
    first.submit(market())
    second = Paper(database, first.gateway)
    second.broker.connect()
    second.submit(market())
    assert len(first.gateway.placed) == 1
    assert second.broker.ignored_duplicates == ("o-buy",)


def test_the_listing_exchange_is_given_only_where_its_code_was_checked(paper: Paper) -> None:
    paper.submit(market("a"))
    paper.submit(_order("b", Side.BUY, "1", OrderType.MARKET, TimeInForce.DAY, instrument=QQQ))
    paper.submit(market("c"))  # SPY again: looked up once
    assert [(q.symbol, q.primary_exchange) for q in paper.gateway.lookups] == [
        ("SPY", "ARCA"),
        ("QQQ", None),
    ]


BRK = Instrument("BRK.B", "XNYS", Currency.USD, "XNYS", AssetClass.STOCK)
AMEX = Instrument("SPY", "ARCX", Currency.USD, "XASE", AssetClass.ETF)


@pytest.mark.parametrize(
    ("order", "reason"),
    [
        (market(quantity="1.5"), "whole shares"),
        (_order("o", Side.BUY, "1", OrderType.STOP, TimeInForce.GTC, "1.00"), "buy stops"),
        (_order("o", Side.SELL, "1", OrderType.STOP, TimeInForce.DAY, "1.00"), "good-till"),
        (_order("o", Side.BUY, "1", OrderType.MARKET, TimeInForce.GTC), "next open"),
        (stop("o", price="450.005"), "whole cents"),
        (_order("o", Side.BUY, "1", OrderType.MARKET, TimeInForce.DAY, instrument=BRK), "BRK.B"),
        (_order("o", Side.BUY, "1", OrderType.MARKET, TimeInForce.DAY, instrument=AMEX), "XASE"),
    ],
    ids=["fraction", "buy-stop", "day-stop", "gtc-market", "sub-cent", "symbol", "calendar"],
)
def test_orders_ibkr_could_not_take_are_rejected_without_sending(
    paper: Paper, order: Order, reason: str
) -> None:
    paper.submit(order)
    assert paper.states(order.client_order_id) == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert reason in paper.last(order.client_order_id).note
    assert paper.last(order.client_order_id).note.startswith("not sent:")
    assert paper.gateway.placed == []
    assert paper.store.get(order.client_order_id) is None


def test_an_instrument_ibkr_cannot_identify_is_rejected(paper: Paper) -> None:
    paper.gateway.contracts["SPY"] = [(1, "ARCA"), (2, "ARCA")]
    paper.submit(market())
    assert paper.last("o-buy").status is OrderStatus.REJECTED
    assert "2 stocks SPY match" in paper.last("o-buy").note
    assert paper.gateway.placed == []


def test_a_connection_lost_while_looking_up_the_contract_sends_nothing(paper: Paper) -> None:
    paper.gateway.connected = False
    paper.submit(market())
    assert paper.last("o-buy").status is OrderStatus.REJECTED
    assert paper.store.get("o-buy") is None


# --- never resend (decided with Pablo, 2026-11-24) -------------------------------------


def test_an_order_lost_before_it_reached_ibkr_is_rejected_and_never_resent(
    paper: Paper,
) -> None:
    paper.gateway.drop = Drop.BEFORE_ARRIVAL
    paper.submit(market())
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED]  # fate unknown
    record = paper.store.get("o-buy")
    assert record is not None
    assert record.fate is Fate.SENDING

    paper.broker.connect()
    report = paper.broker.sync()

    assert report.lost == ("o-buy",)
    assert not report.clean
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert "never resent" in paper.last("o-buy").note
    assert paper.gateway.placed == []
    lost = paper.store.get("o-buy")
    assert lost is not None
    assert lost.fate is Fate.LOST
    assert lost.state.status is OrderStatus.REJECTED

    assert paper.broker.sync().lost == ()  # once only
    paper.submit(market())  # and the same decision cannot send it now
    assert paper.gateway.placed == []


def test_an_order_that_reached_ibkr_is_found_and_tracked_after_reconnecting(
    paper: Paper,
) -> None:
    paper.gateway.drop = Drop.AFTER_ARRIVAL
    paper.submit(market())
    paper.broker.connect()
    report = paper.broker.sync()

    assert report.clean
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED, OrderStatus.ACCEPTED]
    record = paper.store.get("o-buy")
    assert record is not None
    assert (record.fate, record.order_id, record.perm_id) == (Fate.PLACED, 101, 900001)
    assert len(paper.gateway.placed) == 1


def test_an_order_found_only_by_its_execution_is_tracked_and_filled(paper: Paper) -> None:
    paper.gateway.drop = Drop.AFTER_ARRIVAL
    paper.submit(market())
    paper.broker.connect()
    paper.gateway.execute("o-buy", "10", "470.12", OPEN_WED)
    paper.gateway.forget("o-buy")  # an earlier day's order: only today's execution remains

    report = paper.broker.sync()

    assert report.clean
    assert paper.states("o-buy")[-1] is OrderStatus.FILLED
    record = paper.store.get("o-buy")
    assert record is not None
    assert record.fate is Fate.PLACED


def test_sync_needs_the_checked_connection(paper: Paper) -> None:
    paper.broker.close()
    with pytest.raises(IBKRConnectionError):
        paper.broker.sync()
    with pytest.raises(IBKRConnectionError):
        paper.broker.account()


# --- reading back -------------------------------------------------------------------


def test_an_order_waiting_to_be_submitted_stays_submitted(paper: Paper) -> None:
    paper.submit(market())
    paper.gateway.set_status("o-buy", "PendingSubmit")
    assert paper.broker.sync().clean
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED]


def test_a_working_order_is_accepted_once(paper: Paper) -> None:
    paper.submit(market())
    paper.broker.sync()
    paper.gateway.set_status("o-buy", "Submitted")
    paper.broker.sync()
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED, OrderStatus.ACCEPTED]


def test_an_execution_becomes_a_fill_with_ibkrs_price_and_commission(paper: Paper) -> None:
    paper.submit(market())
    execution = paper.gateway.execute("o-buy", "10", "470.12", OPEN_WED, commission="1.0035")
    paper.gateway.set_status("o-buy", "Filled")

    assert paper.broker.sync().clean

    (event,) = paper.fills
    fill = event.fill
    assert fill.fill_id == f"ibkr-{execution.exec_id}"
    assert fill.client_order_id == "o-buy"
    assert (fill.instrument, fill.side, fill.quantity) == (SPY, Side.BUY, Decimal(10))
    assert (fill.price, fill.commission) == (usd("470.12"), usd("1.0035"))
    assert fill.filled_at == OPEN_WED
    assert (fill.trade_date, fill.settles_on) == (date(2024, 1, 3), date(2024, 1, 4))
    assert paper.states("o-buy") == [
        OrderStatus.SUBMITTED,
        OrderStatus.ACCEPTED,
        OrderStatus.FILLED,
    ]
    kinds = [type(e).__name__ for e in paper.recorder.events[1:]]
    assert kinds == ["OrderEvent", "FillEvent", "OrderEvent"]  # fill before its new status


def test_executions_read_again_are_not_published_again_even_after_a_restart(
    database: sqlite3.Connection,
) -> None:
    first = Paper(database)
    first.broker.connect()
    first.submit(market())
    first.gateway.execute("o-buy", "4", "470.12", OPEN_WED)
    first.broker.sync()
    first.broker.sync()
    assert len(first.fills) == 1

    second = Paper(database, first.gateway)
    second.broker.connect()
    first.gateway.execute("o-buy", "6", "470.20", NOON_WED)
    second.broker.sync()
    assert [f.fill.quantity for f in second.fills] == [Decimal(6)]
    assert second.states("o-buy") == [OrderStatus.FILLED]


def test_a_partial_fill_then_ibkrs_cancellation(paper: Paper) -> None:
    paper.submit(market())
    paper.gateway.execute("o-buy", "3", "470.12", OPEN_WED)
    paper.gateway.set_status("o-buy", "Cancelled", "202 Order Canceled - reason: unfilled")
    paper.broker.sync()
    assert paper.states("o-buy") == [
        OrderStatus.SUBMITTED,
        OrderStatus.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCELLED,
    ]
    assert paper.last("o-buy").note == "IBKR: Cancelled: 202 Order Canceled - reason: unfilled"
    assert paper.last("o-buy").filled_quantity == Decimal(3)


@pytest.mark.parametrize("status", ["Cancelled", "ApiCancelled", "Inactive"])
def test_an_order_ibkr_ends_before_working_is_rejected(paper: Paper, status: str) -> None:
    paper.submit(market())
    paper.gateway.set_status("o-buy", status, "201 Order rejected")
    paper.broker.sync()
    assert paper.states("o-buy") == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert paper.last("o-buy").note == f"IBKR: {status}: 201 Order rejected"


def test_an_execution_waits_for_its_commission(paper: Paper) -> None:
    paper.submit(market())
    first = paper.gateway.execute("o-buy", "4", "470.12", OPEN_WED, commission=None)
    paper.gateway.execute("o-buy", "6", "470.20", NOON_WED)

    report = paper.broker.sync()
    assert report.awaiting_commission == (first.exec_id,)
    assert paper.fills == []  # the later one waits too, to keep the order of fills

    paper.gateway.report_commission(first.exec_id, "1.00")
    assert paper.broker.sync().clean
    assert [f.fill.quantity for f in paper.fills] == [Decimal(4), Decimal(6)]


def test_a_correction_is_reported_not_applied(paper: Paper) -> None:
    paper.submit(market())
    paper.gateway.execute("o-buy", "4", "470.12", OPEN_WED, exec_id="0000e0d5.0001.01.01")
    paper.broker.sync()
    paper.gateway.execute("o-buy", "4", "470.10", OPEN_WED, exec_id="0000e0d5.0001.01.02")
    report = paper.broker.sync()
    assert report.corrections == ("0000e0d5.0001.01.02",)
    assert len(paper.fills) == 1


def test_filled_at_ibkr_but_not_by_todays_executions_is_unaccounted(paper: Paper) -> None:
    paper.submit(market())
    paper.gateway.execute("o-buy", "4", "470.12", OPEN_WED)
    paper.gateway.set_status("o-buy", "Filled")
    report = paper.broker.sync()
    assert report.unaccounted == (
        Unaccounted("o-buy", "IBKR says filled, but today's executions cover 4 of 10 shares"),
    )
    assert paper.last("o-buy").status is OrderStatus.PARTIALLY_FILLED


def test_an_order_ibkr_no_longer_lists_is_unaccounted_not_guessed(paper: Paper) -> None:
    paper.submit(stop())
    paper.broker.sync()
    paper.gateway.forget("o-stop")  # e.g. IBKR cancelled the stop at a quarter's end
    report = paper.broker.sync()
    assert [u.client_order_id for u in report.unaccounted] == ["o-stop"]
    assert paper.last("o-stop").status is OrderStatus.ACCEPTED


def test_an_unknown_ibkr_status_is_unaccounted(paper: Paper) -> None:
    paper.submit(market())
    paper.gateway.set_status("o-buy", "WarnState")
    report = paper.broker.sync()
    assert report.unaccounted == (Unaccounted("o-buy", "unknown IBKR status 'WarnState'"),)


def test_executions_of_other_orders_are_counted_not_used(paper: Paper) -> None:
    paper.submit(market())
    mine = paper.gateway.execute("o-buy", "10", "470.12", OPEN_WED)
    paper.gateway.execs.append(replace(mine, exec_id="x", order_ref="pablo"))
    report = paper.broker.sync()
    assert report.foreign_executions == 1
    assert len(paper.fills) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"side": "SLD"}, "is SLD"),
        ({"currency": "CAD"}, "commission in CAD"),
        ({"at": datetime(2024, 1, 3, 23, 0, tzinfo=UTC)}, "outside a XNYS session"),
        ({"at": datetime(2024, 1, 3, 14, 30)}, "no time zone"),  # noqa: DTZ001 - on purpose
        ({"shares": "11"}, "has only 10 left"),
    ],
    ids=["side", "currency", "after-close", "naive-time", "too-many"],
)
def test_an_execution_that_contradicts_its_order_stops_the_run(
    paper: Paper, change: dict[str, object], message: str
) -> None:
    paper.submit(market())
    arguments: dict[str, object] = {"shares": "10", "at": OPEN_WED} | change
    shares = str(arguments.pop("shares"))
    at = arguments.pop("at")
    assert isinstance(at, datetime)
    paper.gateway.execute("o-buy", shares, "470.12", at, **arguments)  # type: ignore[arg-type]
    with pytest.raises(IBKRBrokerError, match=message):
        paper.broker.sync()


def test_an_event_is_recorded_only_once_every_subscriber_has_handled_it(
    database: sqlite3.Connection,
) -> None:
    p = Paper(database)

    def refuse(envelope: Envelope[FillEvent]) -> None:
        raise RuntimeError("the ledger refused it")

    p.bus.subscribe(FillEvent, refuse, name="ledger")
    p.broker.connect()
    p.submit(market())
    execution = p.gateway.execute("o-buy", "10", "470.12", OPEN_WED)
    with pytest.raises(HandlerError):
        p.broker.sync()
    assert not p.store.fill_seen(execution.exec_id)  # the next run sees it again


# --- cancelling ---------------------------------------------------------------------


def test_cancelling_a_placed_order_asks_ibkr(paper: Paper) -> None:
    paper.submit(stop())
    paper.cancel("o-stop")
    assert paper.gateway.cancelled == [101]
    record = paper.store.get("o-stop")
    assert record is not None
    assert record.cancel_requested
    paper.gateway.set_status("o-stop", "Cancelled")
    paper.broker.sync()
    assert paper.states("o-stop") == [
        OrderStatus.SUBMITTED,
        OrderStatus.ACCEPTED,
        OrderStatus.CANCELLED,
    ]


# --- a sale waits for its stop's cancellation (ADR-0045) --------------------------------


def test_a_sale_is_held_until_released_and_a_purchase_is_not(paper: Paper) -> None:
    paper.submit(market("o-sell", Side.SELL), release=False)
    paper.submit(market("o-buy", Side.BUY), release=False)

    assert [t.order_ref for t in paper.gateway.placed] == ["o-buy"]
    assert paper.broker.held == ("o-sell",)
    assert paper.store.get("o-sell") is None  # not even written: nothing has left Tyche

    assert paper.broker.release() == ()
    assert [t.order_ref for t in paper.gateway.placed] == ["o-buy", "o-sell"]


def test_a_sale_waits_until_ibkr_confirms_its_stops_cancellation(paper: Paper) -> None:
    paper.submit(stop("o-stop"))
    # A decision publishes the sale first, then cancels the stop on the same shares.
    paper.submit(market("o-sell", Side.SELL), release=False)
    paper.cancel("o-stop")

    assert paper.broker.release() == ("o-sell",)
    paper.broker.sync()
    assert paper.broker.release() == ("o-sell",)  # IBKR has not confirmed yet

    paper.gateway.set_status("o-stop", "Cancelled")
    paper.broker.sync()
    assert paper.broker.release() == ()
    assert [t.order_ref for t in paper.gateway.placed] == ["o-stop", "o-sell"]


def test_a_replacement_stop_waits_too(paper: Paper) -> None:
    paper.submit(stop("o-stop-old"))
    paper.submit(stop("o-stop-new", quantity="5"), release=False)
    paper.cancel("o-stop-old")

    assert paper.broker.release() == ("o-stop-new",)


def test_a_sale_on_another_instrument_does_not_wait(paper: Paper) -> None:
    paper.submit(stop("o-stop"))
    paper.cancel("o-stop")
    qqq = replace(market("o-sell", Side.SELL), instrument=QQQ)
    paper.submit(qqq, release=False)

    assert paper.broker.release() == ()


def test_what_is_still_held_when_the_cycle_stops_waiting_is_rejected_never_sent(
    paper: Paper,
) -> None:
    paper.submit(stop("o-stop"))
    paper.submit(market("o-sell", Side.SELL), release=False)
    paper.cancel("o-stop")
    paper.broker.release()

    assert paper.broker.reject_held("its stop's cancellation was not confirmed") == ("o-sell",)

    assert paper.broker.held == ()
    assert paper.states("o-sell") == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert "not sent: its stop's cancellation" in (paper.last("o-sell").note or "")
    assert [t.order_ref for t in paper.gateway.placed] == ["o-stop"]
    paper.cancel("o-sell")  # cancelling it later is harmless


def test_cancelling_a_held_order_rejects_it_unsent(paper: Paper) -> None:
    paper.submit(stop("o-stop"), release=False)
    paper.cancel("o-stop")

    assert paper.broker.held == ()
    assert paper.states("o-stop") == [OrderStatus.SUBMITTED, OrderStatus.REJECTED]
    assert paper.gateway.placed == []


def test_releasing_needs_the_connection(paper: Paper) -> None:
    paper.submit(market("o-sell", Side.SELL), release=False)
    paper.broker.close()

    with pytest.raises(IBKRConnectionError):
        paper.broker.release()
    assert paper.broker.held == ("o-sell",)


def test_an_order_reconciliation_dropped_is_forgotten(paper: Paper) -> None:
    paper.submit(stop("o-stop"))
    paper.cancel("o-stop")
    paper.gateway.forget("o-stop")  # IBKR cancelled it on a day no run read
    assert [u.client_order_id for u in paper.broker.sync().unaccounted] == ["o-stop"]

    closed = paper.broker.forget(["o-stop", "never-sent"], "ended: dropped by reconciliation")

    assert closed == ("o-stop",)
    record = paper.store.get("o-stop")
    assert record is not None
    assert record.state.status.is_terminal
    assert record.state.note == "ended: dropped by reconciliation"
    assert paper.broker.sync().unaccounted == ()
    paper.submit(market("o-sell", Side.SELL), release=False)
    assert paper.broker.release() == ()  # no cancellation left waiting


def test_a_cancel_whose_order_was_lost_in_sending_waits_for_the_order_to_be_found(
    paper: Paper,
) -> None:
    paper.gateway.drop = Drop.AFTER_ARRIVAL
    paper.submit(stop())
    paper.broker.connect()
    paper.cancel("o-stop")
    assert paper.gateway.cancelled == []
    paper.broker.sync()
    assert paper.gateway.cancelled == [101]


def test_a_cancel_that_cannot_reach_ibkr_is_asked_again_at_the_next_sync(paper: Paper) -> None:
    paper.submit(stop())
    paper.broker.sync()
    paper.gateway.connected = False
    paper.cancel("o-stop")
    assert paper.gateway.cancelled == []
    paper.broker.connect()
    paper.broker.sync()
    assert paper.gateway.cancelled == [101]


def test_cancels_of_finished_or_unsent_orders_are_ignored(paper: Paper) -> None:
    paper.submit(market(quantity="0.5"))  # rejected before sending
    paper.cancel("o-buy")
    paper.submit(stop())
    paper.gateway.set_status("o-stop", "Cancelled")
    paper.broker.sync()
    paper.cancel("o-stop")
    assert paper.gateway.cancelled == []


def test_cancelling_an_order_never_sent_is_a_bug(paper: Paper) -> None:
    with pytest.raises(HandlerError) as raised:
        paper.cancel("nobody")
    assert isinstance(raised.value.__cause__, IBKRBrokerError)
    assert "never sent" in str(raised.value.__cause__)


# --- the account --------------------------------------------------------------------


def _value(tag: str, value: str, currency: str = "USD") -> ReportedValue:
    return ReportedValue(ACCOUNT, tag, value, currency)


def _holding(symbol: str, quantity: str, cost: str, price: str) -> ReportedHolding:
    return ReportedHolding(ACCOUNT, symbol, "USD", Decimal(quantity), Decimal(cost), Decimal(price))


def test_the_account_is_settled_cash_by_date_and_ibkrs_positions(paper: Paper) -> None:
    paper.gateway.values = [
        _value("SettledCashByDate", "20240103:5000.00;20240104:5300.50;20240105:5300.50"),
        _value("SettledCashByDate", "20240103:5000.00;20240104:5300.50", "BASE"),
        _value("TotalCashValue", "5300.50"),
        ReportedValue("TEST-OTHER", "SettledCashByDate", "20240103:1.00", "USD"),
    ]
    paper.gateway.portfolio = [
        _holding("SPY", "10", "470.2", "472.5"),
        _holding("QQQ", "0", "400", "401"),
    ]

    account = paper.broker.account()

    cash = account.cash(Currency.USD)
    assert cash.settled == usd("5000.00")
    assert [(p.amount, p.settles_on) for p in cash.pending] == [(usd("300.50"), date(2024, 1, 4))]
    (position,) = account.positions
    assert (position.instrument, position.quantity, position.cost) == (
        SPY,
        Decimal(10),
        usd("4702.0"),
    )
    assert account.mark_of(SPY) == usd("472.5")
    assert account.equity(Currency.USD) == usd("10025.50")


@pytest.mark.parametrize(
    ("values", "holdings", "message"),
    [
        ([_value("TotalCashValue", "1")], [], "no SettledCashByDate"),
        ([_value("SettledCashByDate", "2024-01-03:1")], [], "cannot read"),
        ([_value("SettledCashByDate", "20240103:x")], [], "cannot read"),
        ([_value("SettledCashByDate", "20240103:NaN")], [], "not a number"),
        ([_value("SettledCashByDate", "20240104:1;20240103:2")], [], "date order"),
        ([_value("SettledCashByDate", "20240103:1", "JPY")], [], "JPY"),
        ([_value("SettledCashByDate", "20240103:1")], [_holding("IWM", "1", "1", "1")], "IWM"),
        ([_value("SettledCashByDate", "20240103:1")], [_holding("SPY", "1", "1", "0")], "price"),
    ],
    ids=["no-tag", "bad-date", "bad-amount", "nan", "order", "currency", "unknown", "no-price"],
)
def test_an_account_tyche_cannot_read_exactly_is_refused(
    paper: Paper, values: list[ReportedValue], holdings: list[ReportedHolding], message: str
) -> None:
    paper.gateway.values = values
    paper.gateway.portfolio = holdings
    with pytest.raises(IBKRBrokerError, match=message):
        paper.broker.account()


def test_order_returns_the_latest_state(paper: Paper) -> None:
    assert paper.broker.order("o-buy") is None
    paper.submit(market())
    state = paper.broker.order("o-buy")
    assert state is not None
    assert state.status is OrderStatus.SUBMITTED


# --- the record reconciliation reads (ADR-0044) -------------------------------------


def _cash_only(paper: Paper, *extra: ReportedValue) -> None:
    paper.gateway.values = [_value("SettledCashByDate", "20240103:5000.00"), *extra]


def test_the_record_lists_tyches_working_orders_with_what_remains(paper: Paper) -> None:
    _cash_only(paper)
    paper.submit(market())
    paper.submit(stop())
    paper.gateway.execute("o-buy", "4", "470.12", OPEN_WED)
    paper.gateway.set_status("o-buy", "Submitted")
    paper.broker.sync()
    paper.gateway.orders[paper.gateway.order_for("o-buy").order_id] = replace(
        paper.gateway.order_for("o-buy"), filled=Decimal(4), remaining=Decimal(6)
    )

    record = paper.broker.record()

    assert record.orders == (BrokerOrder("o-buy", Decimal(6)), BrokerOrder("o-stop", Decimal(10)))
    assert (record.foreign_orders, record.unresolved, record.accrued_dividends) == (0, (), ())
    assert record.account == paper.broker.account()


def test_an_order_ibkr_no_longer_lists_is_not_in_the_record(paper: Paper) -> None:
    _cash_only(paper)
    paper.submit(stop())
    paper.gateway.forget("o-stop")

    assert paper.broker.record().orders == ()


def test_working_orders_that_are_not_tyches_are_counted(paper: Paper) -> None:
    _cash_only(paper)
    theirs = ReportedOrder("", 7, 1, ACCOUNT, "Submitted", Decimal(0), Decimal(5))
    elsewhere = ReportedOrder("", 8, 2, "TEST-OTHER", "Submitted", Decimal(0), Decimal(5))
    paper.gateway.orders.update({7: theirs, 8: elsewhere})

    assert paper.broker.record().foreign_orders == 1


def test_an_open_order_in_a_status_tyche_does_not_know_is_unresolved(paper: Paper) -> None:
    _cash_only(paper)
    paper.submit(market())
    paper.gateway.set_status("o-buy", "Mystery")

    (note,) = paper.broker.record().unresolved
    assert "o-buy" in note
    assert "Mystery" in note


def test_what_the_last_sync_could_not_settle_is_unresolved(paper: Paper) -> None:
    _cash_only(paper)
    paper.submit(market())
    paper.gateway.execute("o-buy", "10", "470.12", OPEN_WED, exec_id="0001.01", commission=None)
    paper.broker.sync()

    assert paper.broker.record().unresolved == (
        "execution 0001.01 awaits IBKR's commission report",
    )


def test_accrued_dividends_per_currency_not_the_base(paper: Paper) -> None:
    _cash_only(
        paper,
        _value("AccruedDividend", "18.25"),
        _value("AccruedDividend", "24.90", "BASE"),
        _value("AccruedDividend", "0.00", "CAD"),
    )

    assert paper.broker.record().accrued_dividends == (usd("18.25"),)


@pytest.mark.parametrize("text", ["x", "NaN", "-1"])
def test_an_accrued_dividend_tyche_cannot_read_is_refused(paper: Paper, text: str) -> None:
    _cash_only(paper, _value("AccruedDividend", text))

    with pytest.raises(IBKRBrokerError):
        paper.broker.record()

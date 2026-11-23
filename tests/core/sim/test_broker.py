"""SimBroker: when orders work, how they fill, what they cost, and what it refuses."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.support.costs import NO_FEES, US_COSTS, usd
from tests.support.ledger import fill as ledger_fill
from tests.support.market import QQQ, SPY, close_of, dividend, session
from tests.support.recording import TickingClock
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    Account,
    AssetClass,
    Bar,
    BarHistory,
    CashDistribution,
    Currency,
    Instrument,
    Money,
    Order,
    OrderState,
    OrderStatus,
    OrderType,
    PriceAdjustment,
    Side,
    Timeframe,
    TimeInForce,
    TradingCosts,
)
from tyche.core.engine import Engine
from tyche.core.events import (
    BarEvent,
    CancelRequestEvent,
    DataReadyEvent,
    DistributionEvent,
    Envelope,
    Event,
    EventBus,
    FillEvent,
    HandlerError,
    OrderEvent,
    RunMode,
    SessionEvent,
    SessionPhase,
)
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.sim import HistoricalReplay, SimBroker, SimBrokerError, SimClock

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
CALENDARS = {"XNYS": NYSE}

# Exact arithmetic for most tests: no slippage, no regulatory fees, Fixed commission.
PLAIN = replace(US_COSTS, slippage_bps=Decimal(0), regulatory_fees=NO_FEES)

TUE, WED, THU, FRI, MON = (date(2024, 1, d) for d in (2, 3, 4, 5, 8))


def ohlc(
    day: date,
    open_: str,
    high: str | None = None,
    low: str | None = None,
    close: str | None = None,
    *,
    volume: float = 1_000_000.0,
    instrument: Instrument = SPY,
) -> Bar:
    o = float(open_)
    return Bar(
        instrument=instrument,
        timeframe=Timeframe.D1,
        timestamp=close_of(day),
        open=o,
        high=float(high) if high else o,
        low=float(low) if low else o,
        close=float(close) if close else o,
        volume=volume,
        adjustment=PriceAdjustment.SPLITS,
    )


def order(
    order_id: str,
    side: Side = Side.BUY,
    quantity: str = "10",
    *,
    instrument: Instrument = SPY,
    stop: str | None = None,
    tif: TimeInForce = TimeInForce.DAY,
) -> Order:
    return Order(
        client_order_id=order_id,
        instrument=instrument,
        side=side,
        quantity=Decimal(quantity),
        order_type=OrderType.STOP if stop else OrderType.MARKET,
        time_in_force=tif,
        created_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        reason="test",
        stop_price=Money.of(stop, instrument.currency) if stop else None,
    )


def holding(quantity: str, cash: str = "10000") -> Account:
    """``quantity`` SPY bought at 100 before the tests start, fully settled, with ``cash`` left."""
    bought = ledger_fill(Side.BUY, quantity, "100", commission="1", trade_date=date(2023, 12, 28))
    funded = Account.empty().deposit(usd(cash) - bought.cash_flow)
    return funded.apply_fill(bought).settle(date(2023, 12, 29))


class Market:
    """Drives a SimBroker the way the replay and execution will: inputs, then drain."""

    def __init__(
        self,
        account: Account | None = None,
        costs: TradingCosts = PLAIN,
        participation: Decimal = Decimal(1),
    ) -> None:
        self.bus = EventBus(TickingClock().now)
        self.broker = SimBroker(
            self.bus,
            account or Account.empty().deposit(usd("10000")),
            costs,
            CALENDARS,
            max_volume_participation=participation,
        )
        self.seen: list[Event] = []
        self.bus.subscribe(Event, self._record, name="recorder")

    def _record(self, envelope: Envelope[Event]) -> None:
        self.seen.append(envelope.event)

    def submit(self, *orders: Order) -> None:
        for o in orders:
            self.bus.publish(OrderEvent(OrderState(o).submit()), source="execution")
        self.bus.drain()

    def trade(
        self, day: date, *bars: Bar, distributions: tuple[CashDistribution, ...] = ()
    ) -> None:
        """One session: open, distributions, bars, close."""
        today = session(day)
        inputs: list[Event] = [SessionEvent(today, SessionPhase.OPEN)]
        inputs += [DistributionEvent(d) for d in distributions]
        inputs += [BarEvent(b) for b in bars]
        inputs.append(SessionEvent(today, SessionPhase.CLOSE))
        for event in inputs:
            self.bus.publish(event, source="feed")
            self.bus.drain()

    def fills(self) -> list[FillEvent]:
        return [e for e in self.seen if isinstance(e, FillEvent)]

    def statuses(self, order_id: str) -> list[OrderStatus]:
        return [
            e.state.status
            for e in self.seen
            if isinstance(e, OrderEvent) and e.state.order.client_order_id == order_id
        ]

    def state(self, order_id: str) -> OrderState:
        state = self.broker.order(order_id)
        assert state is not None
        return state


class TestMarketOrders:
    def test_an_order_works_from_the_next_open_and_fills_at_the_open(self) -> None:
        market = Market()
        market.submit(order("buy-1"))

        assert market.statuses("buy-1") == [OrderStatus.SUBMITTED, OrderStatus.ACCEPTED]

        market.trade(WED, ohlc(WED, "100", "103", "99", "102"))

        [event] = market.fills()
        fill = event.fill
        assert (fill.quantity, fill.price, fill.commission) == (Decimal(10), usd("100"), usd("1"))
        assert fill.filled_at == session(WED).opens_at
        assert (fill.trade_date, fill.settles_on) == (WED, THU)
        assert market.statuses("buy-1")[-1] is OrderStatus.FILLED

    def test_the_fill_is_published_before_the_order_status(self) -> None:
        market = Market()
        market.submit(order("buy-1"))
        market.trade(WED, ohlc(WED, "100"))

        kinds = [type(e).__name__ for e in market.seen if isinstance(e, FillEvent | OrderEvent)]
        assert kinds[-2:] == ["FillEvent", "OrderEvent"]

    def test_the_account_records_the_purchase_unsettled_and_marks_at_the_close(self) -> None:
        market = Market()
        market.submit(order("buy-1"))
        market.trade(WED, ohlc(WED, "100", "103", "99", "102"))

        account = market.broker.account()
        position = account.position(SPY)
        assert position is not None
        assert position.quantity == 10
        assert account.cash(Currency.USD).settled == usd("10000")
        assert account.cash(Currency.USD).unsettled == usd("-1001")
        assert account.mark_of(SPY) == usd("102")

    def test_pending_cash_settles_at_the_open_of_its_settlement_date(self) -> None:
        market = Market()
        market.submit(order("buy-1"))
        market.trade(WED, ohlc(WED, "100"))
        market.trade(THU, ohlc(THU, "100"))

        assert market.broker.account().cash(Currency.USD).settled == usd("8999")

    def test_slippage_and_fees_are_charged(self) -> None:
        market = Market(costs=US_COSTS)
        market.submit(order("buy-1"))
        market.trade(WED, ohlc(WED, "100"))

        [event] = market.fills()
        assert event.fill.price == usd("100.05")
        assert event.fill.commission == usd("1.01")  # 1.00 commission + 0.01 audit-trail fee

    def test_a_day_order_with_no_bar_expires_at_the_close(self) -> None:
        market = Market()
        market.submit(order("buy-1"))
        market.trade(WED)  # no SPY bar: a halt, or missing data

        assert market.statuses("buy-1")[-1] is OrderStatus.EXPIRED
        assert market.fills() == []

    def test_orders_fill_in_the_order_they_were_submitted(self) -> None:
        market = Market()
        market.submit(order("first", quantity="1"), order("second", quantity="2"))
        market.trade(WED, ohlc(WED, "100"))

        assert [f.fill.client_order_id for f in market.fills()] == ["first", "second"]

    def test_fill_ids_are_unique_and_deterministic(self) -> None:
        market = Market()
        market.submit(order("a", quantity="1"), order("b", quantity="1"))
        market.trade(WED, ohlc(WED, "100"))

        assert [f.fill.fill_id for f in market.fills()] == ["sim-000001", "sim-000002"]


class TestSubmission:
    @pytest.mark.parametrize(
        ("submitted", "reason"),
        [
            (order("frac", quantity="1.5"), "whole shares only"),
            (order("buy-stop", stop="105"), "buy stops are not supported"),
            (order("short", Side.SELL), "cannot sell 10 SPY@ARCX: 0 held"),
            (
                order(
                    "cad",
                    instrument=Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF),
                ),
                "trades in CAD, but this broker's costs are in USD",
            ),
            (
                order(
                    "tsx",
                    instrument=Instrument("RY", "XNYS", Currency.USD, "XTSE", AssetClass.STOCK),
                ),
                "no calendar loaded for XTSE",
            ),
        ],
    )
    def test_rejects_what_it_cannot_trade(self, submitted: Order, reason: str) -> None:
        market = Market()
        market.submit(submitted)

        state = market.state(submitted.client_order_id)
        assert state.status is OrderStatus.REJECTED
        assert reason in state.note

    def test_a_repeated_order_id_is_ignored(self) -> None:
        market = Market()
        market.submit(order("buy-1"), order("buy-1", quantity="20"))
        market.trade(WED, ohlc(WED, "100"))

        assert [f.fill.quantity for f in market.fills()] == [Decimal(10)]
        assert market.broker.ignored_duplicates == ("buy-1",)

    def test_ignores_statuses_it_did_not_receive_as_submissions(self) -> None:
        market = Market()
        created = OrderState(order("x"))
        market.bus.publish(OrderEvent(created), source="execution")
        market.bus.drain()

        assert market.broker.order("x") is None


class TestSettledCash:
    def test_a_purchase_cannot_use_unsettled_sale_proceeds(self) -> None:
        market = Market(holding("10", cash="100"))
        market.submit(order("sell", Side.SELL), order("buy", quantity="5", instrument=QQQ))
        market.trade(WED, ohlc(WED, "100"), ohlc(WED, "50", instrument=QQQ))

        assert market.statuses("sell")[-1] is OrderStatus.FILLED
        state = market.state("buy")
        assert state.status is OrderStatus.CANCELLED
        assert "insufficient settled cash at the open: needs 251.00 USD, has 100.00" in state.note

    def test_the_proceeds_can_be_spent_once_settled(self) -> None:
        market = Market(holding("10", cash="100"))
        market.submit(order("sell", Side.SELL))
        market.trade(WED, ohlc(WED, "100"))
        market.submit(order("buy", quantity="5", instrument=QQQ))
        market.trade(THU, ohlc(THU, "50", instrument=QQQ))

        assert market.statuses("buy")[-1] is OrderStatus.FILLED

    def test_two_purchases_at_one_open_cannot_spend_the_same_cash(self) -> None:
        market = Market(Account.empty().deposit(usd("1000")))
        market.submit(
            order("buy-spy", quantity="6"), order("buy-qqq", quantity="6", instrument=QQQ)
        )
        market.trade(WED, ohlc(WED, "100"), ohlc(WED, "100", instrument=QQQ))

        assert market.state("buy-spy").status is OrderStatus.FILLED
        state = market.state("buy-qqq")
        assert state.status is OrderStatus.CANCELLED
        assert "needs 601.00 USD, has 399.00 USD" in state.note

    def test_the_whole_order_is_cancelled_rather_than_shrunk(self) -> None:
        market = Market(Account.empty().deposit(usd("1000")))
        market.submit(order("buy", quantity="10"))
        market.trade(WED, ohlc(WED, "100"))  # needs 1,001 with the commission

        assert market.state("buy").status is OrderStatus.CANCELLED
        assert market.fills() == []


class TestCancellation:
    def cancel(self, market: Market, order_id: str, reason: str = "replaced") -> None:
        market.bus.publish(CancelRequestEvent(order_id, reason), source="execution")
        market.bus.drain()

    def test_an_open_order_is_cancelled_at_once_with_the_reason(self) -> None:
        market = Market(holding("10"))
        market.submit(order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC))
        self.cancel(market, "stop", "the strategy moved its stop")

        state = market.state("stop")
        assert (state.status, state.note) == (OrderStatus.CANCELLED, "the strategy moved its stop")
        market.trade(WED, ohlc(WED, "100", low="90"))
        assert market.fills() == []

    def test_a_request_for_a_finished_order_is_ignored(self) -> None:
        market = Market()
        market.submit(order("buy"))
        market.trade(WED, ohlc(WED, "100"))
        self.cancel(market, "buy")

        assert market.statuses("buy")[-1] is OrderStatus.FILLED
        assert market.state("buy").status is OrderStatus.FILLED

    def test_a_request_for_an_unknown_order_halts_the_run(self) -> None:
        market = Market()

        with pytest.raises(HandlerError, match="sim-broker") as raised:
            self.cancel(market, "ghost")
        assert "never submitted" in str(raised.value.__cause__)


class TestPartialFills:
    def test_a_bar_fills_at_most_its_share_of_volume_and_the_rest_expires(self) -> None:
        market = Market(participation=Decimal("0.01"))
        market.submit(order("buy", quantity="10"))
        market.trade(WED, ohlc(WED, "100", volume=500.0))  # 1% of 500 is 5 shares

        assert [f.fill.quantity for f in market.fills()] == [Decimal(5)]
        assert market.statuses("buy")[-2:] == [OrderStatus.PARTIALLY_FILLED, OrderStatus.EXPIRED]
        assert market.state("buy").filled_quantity == 5

    def test_orders_share_the_volume_of_a_bar(self) -> None:
        market = Market(participation=Decimal("0.01"))
        market.submit(order("a", quantity="4"), order("b", quantity="4"))
        market.trade(WED, ohlc(WED, "100", volume=500.0))

        assert [f.fill.quantity for f in market.fills()] == [Decimal(4), Decimal(1)]

    def test_volume_resets_each_session(self) -> None:
        market = Market(participation=Decimal("0.01"))
        market.submit(order("a", quantity="5"))
        market.trade(WED, ohlc(WED, "100", volume=500.0))
        market.submit(order("b", quantity="5"))
        market.trade(THU, ohlc(THU, "100", volume=500.0))

        assert [f.fill.quantity for f in market.fills()] == [Decimal(5), Decimal(5)]

    def test_no_fill_when_the_bar_is_too_thin(self) -> None:
        market = Market(participation=Decimal("0.01"))
        market.submit(order("buy", quantity="1"))
        market.trade(WED, ohlc(WED, "100", volume=50.0))

        assert market.fills() == []
        assert market.state("buy").status is OrderStatus.EXPIRED

    @pytest.mark.parametrize("participation", ["0", "-0.1", "1.5", "NaN"])
    def test_refuses_an_impossible_participation(self, participation: str) -> None:
        with pytest.raises(ValueError, match="max_volume_participation"):
            Market(participation=Decimal(participation))


class TestStops:
    def test_a_gap_through_the_stop_fills_at_the_open(self) -> None:
        market = Market(holding("10"))
        market.submit(order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC))
        market.trade(WED, ohlc(WED, "90", "92", "88", "91"))

        [event] = market.fills()
        assert event.fill.price == usd("90")
        assert event.fill.filled_at == session(WED).opens_at

    def test_a_stop_reached_during_the_session_fills_at_the_stop(self) -> None:
        market = Market(holding("10"))
        market.submit(order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC))
        market.trade(WED, ohlc(WED, "100", "101", "94", "99"))

        [event] = market.fills()
        assert event.fill.price == usd("95")
        assert event.fill.filled_at == session(WED).closes_at

    def test_slippage_applies_to_a_stop_fill(self) -> None:
        market = Market(holding("10"), costs=replace(PLAIN, slippage_bps=Decimal(10)))
        market.submit(order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC))
        market.trade(WED, ohlc(WED, "100", "101", "94", "99"))

        assert market.fills()[0].fill.price == usd("94.905")

    def test_a_good_till_cancelled_stop_waits_until_it_triggers(self) -> None:
        market = Market(holding("10"))
        market.submit(order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC))
        market.trade(WED, ohlc(WED, "100", "101", "96", "99"))

        assert market.state("stop").status is OrderStatus.ACCEPTED

        market.trade(THU, ohlc(THU, "99", "99", "94", "95"))

        assert market.state("stop").status is OrderStatus.FILLED
        assert market.fills()[0].fill.trade_date == THU

    def test_a_day_stop_that_does_not_trigger_expires(self) -> None:
        market = Market(holding("10"))
        market.submit(order("stop", Side.SELL, stop="95"))
        market.trade(WED, ohlc(WED, "100", "101", "96", "99"))

        assert market.state("stop").status is OrderStatus.EXPIRED

    def test_a_stop_for_shares_already_sold_is_cancelled_when_it_triggers(self) -> None:
        market = Market(holding("10"))
        market.submit(
            order("exit", Side.SELL),
            order("stop", Side.SELL, stop="95", tif=TimeInForce.GTC),
        )
        market.trade(WED, ohlc(WED, "100", "101", "94", "99"))

        assert market.state("exit").status is OrderStatus.FILLED
        state = market.state("stop")
        assert state.status is OrderStatus.CANCELLED
        assert "only 0 held" in state.note


class TestFreeRiding:
    def test_selling_before_the_purchase_settles_is_recorded(self) -> None:
        market = Market(costs=replace(PLAIN, settlement_days=2))
        market.submit(order("buy"))
        market.trade(WED, ohlc(WED, "100"))  # settles Friday
        market.submit(order("sell", Side.SELL))
        market.trade(THU, ohlc(THU, "100"))

        [violation] = market.broker.free_riding
        assert violation.client_order_id == "sell"
        assert (violation.trade_date, violation.quantity) == (THU, Decimal(10))
        assert violation.purchase_settles_on == FRI

    def test_selling_on_the_settlement_date_is_not_free_riding(self) -> None:
        market = Market()
        market.submit(order("buy"))
        market.trade(WED, ohlc(WED, "100"))  # settles Thursday
        market.submit(order("sell", Side.SELL))
        market.trade(THU, ohlc(THU, "100"))

        assert market.statuses("sell")[-1] is OrderStatus.FILLED
        assert market.broker.free_riding == ()

    def test_sales_are_matched_to_the_oldest_purchase_first(self) -> None:
        market = Market(holding("10"), costs=replace(PLAIN, settlement_days=2))
        market.submit(order("buy"))
        market.trade(WED, ohlc(WED, "100"))
        market.submit(order("sell", Side.SELL, quantity="15"))
        market.trade(THU, ohlc(THU, "100"))

        [violation] = market.broker.free_riding
        assert violation.quantity == Decimal(5)  # the first 10 came from the old, settled lot


class TestDistributions:
    def test_holders_are_paid_at_the_ex_date_open_as_settled_cash(self) -> None:
        market = Market(holding("10", cash="100"))
        market.trade(WED, ohlc(WED, "100"), distributions=(dividend(WED, "0.555"),))

        account = market.broker.account()
        assert account.cash(Currency.USD).settled == usd("105.55")  # 100 + 5.55
        assert account.distributions_received(Currency.USD) == usd("5.55")

    def test_shares_bought_on_the_ex_date_are_not_paid(self) -> None:
        market = Market()
        market.submit(order("buy"))
        market.trade(WED, ohlc(WED, "100"), distributions=(dividend(WED, "0.50"),))

        assert market.broker.account().distributions_received(Currency.USD) == usd("0")

    def test_a_tiny_payment_that_rounds_to_zero_is_skipped(self) -> None:
        market = Market(holding("1"))
        market.trade(WED, ohlc(WED, "100"), distributions=(dividend(WED, "0.001"),))

        assert market.broker.account().distributions_received(Currency.USD) == usd("0")


class TestFailClosed:
    def test_a_bar_outside_an_open_session_halts_the_run(self) -> None:
        market = Market()
        market.bus.publish(BarEvent(ohlc(WED, "100")), source="feed")

        with pytest.raises(HandlerError, match="sim-broker"):
            market.bus.drain()


class OneShotBuyer:
    """A stand-in for execution: buys once, at the first decision cycle."""

    def __init__(self, bus: EventBus) -> None:
        self._done = False
        bus.subscribe(DataReadyEvent, self._decide, name="execution")
        self._bus = bus

    def _decide(self, envelope: Envelope[DataReadyEvent]) -> None:
        if not self._done:
            self._done = True
            self._bus.publish(OrderEvent(OrderState(order("buy-1")).submit()))


def test_end_to_end_with_the_replay_and_the_engine() -> None:
    days = [TUE, WED, THU]
    history = BarHistory(
        SPY,
        tuple(ohlc(d, "100", "101", "99", "100") for d in days),
        distributions=(dividend(THU, "1.00"),),
    )
    replay = HistoricalReplay([history], CALENDARS, TUE, THU)
    clock = SimClock(replay.start or close_of(TUE))
    bus = EventBus(clock.now)
    broker = SimBroker(bus, Account.empty().deposit(usd("5000")), PLAIN, CALENDARS)
    OneShotBuyer(bus)
    journal = InMemoryJournal(bus)

    result = Engine(bus, clock, run_id="t", mode=RunMode.BACKTEST, code_version="test").run(replay)

    assert result.completed, result.failure
    [fill_entry] = journal.of_type(FillEvent)
    assert fill_entry.event.fill.trade_date == WED  # decided at Tuesday's close
    assert fill_entry.cycle_id is None  # a fill arrives between cycles
    causes = [type(e.event).__name__ for e in journal.causes_of(fill_entry)]
    assert causes == ["FillEvent", "BarEvent"]
    accepted = next(
        e for e in journal.of_type(OrderEvent) if e.event.state.status is OrderStatus.ACCEPTED
    )
    assert accepted.cycle_id == "XNYS:2024-01-02:1d"
    account = broker.account()
    assert account.distributions_received(Currency.USD) == usd("10")
    assert account.cash(Currency.USD).settled == usd("4009")  # 5000 - 1001 + 10


def test_its_state_can_only_be_taken_between_sessions() -> None:
    market = Market()
    market.bus.publish(SessionEvent(session(TUE), SessionPhase.OPEN), source="replay")
    market.bus.drain()

    with pytest.raises(SimBrokerError, match="only be taken between sessions"):
        market.broker.state()


def test_a_resumed_broker_has_the_same_state() -> None:
    market = Market(holding("10"))
    market.submit(order("stop-1", Side.SELL, "4", stop="90", tif=TimeInForce.GTC))

    state = market.broker.state()
    resumed = SimBroker.resume(EventBus(TickingClock().now), state, PLAIN, CALENDARS)

    assert resumed.state() == state
    assert resumed.account() == market.broker.account()

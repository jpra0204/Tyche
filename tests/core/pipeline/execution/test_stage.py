"""ExecutionStage against the simulated broker: sizing, the band, crossing, netting, stops.

Each test drives sessions the way the replay does (open, bars, close, then the decision
at the close) with a ``SimBroker`` and ``AccountState`` on the same bus, and publishes
the approved portfolio by hand, as the risk gate would.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.support.costs import NO_FEES, US_COSTS, usd
from tests.support.ledger import fill
from tests.support.market import QQQ, SPY, close_of, session
from tests.support.recording import Recorder, TickingClock
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    Account,
    Bar,
    Contribution,
    ExecutionRules,
    Instrument,
    InstrumentTarget,
    OrderStatus,
    OrderType,
    PlanLine,
    PlanNote,
    PriceAdjustment,
    Side,
    Sleeve,
    SleeveStatus,
    Timeframe,
    TimeInForce,
)
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    CancelRequestEvent,
    Event,
    EventBus,
    ExecutionPlanEvent,
    FillEvent,
    HandlerError,
    OrderEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.pipeline.execution import AccountState, ExecutionError, ExecutionStage, SleeveBook
from tyche.core.ports import Calendar
from tyche.core.sim import SimBroker

D = Decimal
NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
CALENDARS = {"XNYS": NYSE}
PLAIN = replace(US_COSTS, slippage_bps=D(0), regulatory_fees=NO_FEES)
RULES = ExecutionRules(rebalance_band=D("0.10"), price_buffer=D(0))
TUE, WED, THU, FRI, MON = (date(2024, 1, d) for d in (2, 3, 4, 5, 8))
ALL_VOLUME = D(1)


def ohlc(
    day: date,
    open_: str,
    low: str | None = None,
    close: str | None = None,
    *,
    instrument: Instrument = SPY,
    volume: float = 1_000_000.0,
) -> Bar:
    o = float(open_)
    lo = float(low) if low else o
    c = float(close) if close else o
    return Bar(
        instrument=instrument,
        timeframe=Timeframe.D1,
        timestamp=close_of(day),
        open=o,
        high=max(o, c),
        low=min(lo, o, c),
        close=c,
        volume=volume,
        adjustment=PriceAdjustment.SPLITS,
    )


def decided(strategy_id: str, budget: str, *on: Instrument) -> Sleeve:
    return Sleeve(strategy_id, D(budget), SleeveStatus.DECIDED, on, "1")


def failed(strategy_id: str, budget: str) -> Sleeve:
    return Sleeve(strategy_id, D(budget), SleeveStatus.FAILED, error="boom")


def wants(instrument: Instrument, *parts: tuple[str, str, str | None]) -> InstrumentTarget:
    """``parts``: (strategy id, weight of equity, stop price or None)."""
    return InstrumentTarget(
        instrument,
        tuple(
            Contribution(s, D(w), f"{s} wants it", usd(stop) if stop else None)
            for s, w, stop in parts
        ),
    )


class Desk:
    """Execution, account state and the simulated broker on one bus."""

    def __init__(
        self,
        cash: str = "10000",
        *,
        rules: ExecutionRules = RULES,
        participation: Decimal = ALL_VOLUME,
        start: Account | None = None,
        calendars: Mapping[str, Calendar] = CALENDARS,
    ) -> None:
        account = start or Account.empty().deposit(usd(cash))
        self.bus = EventBus(TickingClock().now)
        self.broker = SimBroker(
            self.bus, account, PLAIN, calendars, max_volume_participation=participation
        )
        self.state = AccountState(self.bus, account)
        self.book = SleeveBook()
        ExecutionStage(self.bus, self.book, PLAIN, calendars, rules)
        self.recorder = Recorder(self.bus)

    def trade(self, day: date, *bars: Bar) -> None:
        today = session(day)
        inputs: list[Event] = [SessionEvent(today, SessionPhase.OPEN)]
        inputs += [BarEvent(b) for b in bars]
        inputs.append(SessionEvent(today, SessionPhase.CLOSE))
        for event in inputs:
            self.bus.publish(event, source="feed")
            self.bus.drain()

    def decide(
        self, day: date, sleeves: tuple[Sleeve, ...], *targets: InstrumentTarget
    ) -> list[Event]:
        """Publish the approved portfolio for ``day``'s close; return what it caused."""
        before = len(self.recorder)
        approved = ApprovedPortfolioEvent(close_of(day), sleeves, targets, "pass-through")
        self.bus.publish(approved, source="risk", cycle_id=f"XNYS:{day.isoformat()}:1d")
        self.bus.drain()
        return self.recorder.events[before + 1 :]

    def submitted(self, events: list[Event]) -> list[tuple[str, Side, Decimal, OrderType]]:
        return [
            (o.client_order_id, o.side, o.quantity, o.order_type)
            for e in events
            if isinstance(e, OrderEvent) and e.state.status is OrderStatus.SUBMITTED
            for o in [e.state.order]
        ]

    def plan(self, events: list[Event]) -> tuple[PlanLine, ...]:
        [event] = [e for e in events if isinstance(e, ExecutionPlanEvent)]
        return event.lines

    def fills(self) -> list[FillEvent]:
        return [e for e in self.recorder.events if isinstance(e, FillEvent)]


class TestSizing:
    def test_a_weight_becomes_whole_shares_of_equity_at_the_last_close(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        assert desk.submitted(caused) == [
            ("20240102T210000Z-SPY.ARCX-buy", Side.BUY, D(50), OrderType.MARKET)
        ]
        assert desk.plan(caused) == (PlanLine("a", SPY, D(0), D(50), ordered=D(50)),)

    def test_the_plan_comes_before_the_orders(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        kinds = [type(e).__name__ for e in caused]
        assert kinds.index("ExecutionPlanEvent") < kinds.index("OrderEvent")

    def test_a_fill_belongs_to_the_sleeve_and_shows_as_its_position(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))
        desk.trade(WED, ohlc(WED, "101"))

        [position] = desk.book.positions_of("a")
        assert (position.quantity, position.entry_date, position.entry_price) == (
            D(50),
            WED,
            usd("101"),
        )
        assert position.stop_price is None

    def test_a_weight_worth_less_than_one_share_is_not_held(self) -> None:
        desk = Desk("100")
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        assert desk.submitted(caused) == []
        assert desk.plan(caused) == (PlanLine("a", SPY, D(0), D(0), note=PlanNote.BELOW_ONE_SHARE),)

    def test_the_same_decision_twice_is_handled_once(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        sleeves = (decided("a", "1", SPY),)
        desk.decide(TUE, sleeves, wants(SPY, ("a", "0.5", None)))

        assert desk.decide(TUE, sleeves, wants(SPY, ("a", "0.5", None))) == []


class TestTheBand:
    def setup_desk(self) -> Desk:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))
        desk.trade(WED, ohlc(WED, "100"))  # 50 shares at 100, 4,999 cash left
        return desk

    def test_a_small_drift_is_kept(self) -> None:
        desk = self.setup_desk()

        caused = desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.52", None)))

        assert desk.submitted(caused) == []
        assert desk.plan(caused) == (PlanLine("a", SPY, D(50), D(50), note=PlanNote.WITHIN_BAND),)

    def test_a_drift_beyond_the_band_is_resized(self) -> None:
        desk = self.setup_desk()

        caused = desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.6", None)))

        assert desk.submitted(caused) == [
            ("20240103T210000Z-SPY.ARCX-buy", Side.BUY, D(9), OrderType.MARKET)
        ]

    def test_an_exit_always_trades(self) -> None:
        desk = self.setup_desk()

        caused = desk.decide(WED, (decided("a", "1", SPY),))  # decided on SPY, no target

        assert desk.submitted(caused) == [
            ("20240103T210000Z-SPY.ARCX-sell", Side.SELL, D(50), OrderType.MARKET)
        ]
        assert desk.plan(caused) == (PlanLine("a", SPY, D(50), D(0), ordered=D(-50)),)

    def test_a_failed_sleeve_keeps_what_it_holds(self) -> None:
        desk = self.setup_desk()

        caused = desk.decide(WED, (failed("a", "1"),))

        assert desk.submitted(caused) == []
        assert desk.plan(caused) == (PlanLine("a", SPY, D(50), D(50), note=PlanNote.KEEP),)

    def test_an_instrument_not_offered_is_kept(self) -> None:
        desk = self.setup_desk()

        caused = desk.decide(WED, (decided("a", "1"),))  # SPY not offered this cycle

        assert desk.submitted(caused) == []
        assert desk.book.held("a", SPY) == 50


class TestCrossingAndNetting:
    def two_sleeves_holding_spy(self) -> Desk:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(
            TUE,
            (decided("a", "0.5", SPY), decided("b", "0.5", SPY)),
            wants(SPY, ("a", "0.2", None), ("b", "0.2", None)),
        )
        desk.trade(WED, ohlc(WED, "100"))  # a and b hold 20 each; 5,999 cash left
        return desk

    def test_wishes_that_cancel_out_cross_between_sleeves_without_an_order(self) -> None:
        desk = self.two_sleeves_holding_spy()

        caused = desk.decide(
            WED,
            (decided("a", "0.5", SPY), decided("b", "0.5", SPY)),
            # Equity is 9,998 after two commissions: 0.41 of it is 40 shares. a exits and b
            # doubles, so 20 shares change sleeve.
            wants(SPY, ("b", "0.41", None)),
        )

        assert desk.submitted(caused) == []
        assert desk.plan(caused) == (
            PlanLine("a", SPY, D(20), D(0), crossed=D(-20)),
            PlanLine("b", SPY, D(20), D(40), crossed=D(20)),
        )
        assert desk.book.held("a", SPY) == 0
        [position] = desk.book.positions_of("b")
        assert (position.quantity, position.entry_price) == (D(40), usd("100"))

    def test_what_does_not_cross_is_netted_into_one_order(self) -> None:
        desk = self.two_sleeves_holding_spy()

        caused = desk.decide(
            WED,
            (decided("a", "0.5", SPY), decided("b", "0.5", SPY)),
            wants(SPY, ("a", "0.1001", None), ("b", "0.41", None)),  # a gives 10, b wants 20
        )

        assert desk.submitted(caused) == [
            ("20240103T210000Z-SPY.ARCX-buy", Side.BUY, D(10), OrderType.MARKET)
        ]
        assert desk.plan(caused) == (
            PlanLine("a", SPY, D(20), D(10), crossed=D(-10)),
            PlanLine("b", SPY, D(20), D(40), crossed=D(10), ordered=D(10)),
        )
        desk.trade(THU, ohlc(THU, "100"))
        assert (desk.book.held("a", SPY), desk.book.held("b", SPY)) == (D(10), D(40))

    def test_a_partial_fill_is_split_in_proportion_to_what_each_is_owed(self) -> None:
        desk = Desk(participation=D("0.01"))
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(
            TUE,
            (decided("a", "0.5", SPY), decided("b", "0.5", SPY)),
            wants(SPY, ("a", "0.3", None), ("b", "0.1", None)),  # 30 and 10 shares
        )
        desk.trade(WED, ohlc(WED, "100", volume=2_000.0))  # 1% of volume: 20 shares fill

        assert [f.fill.quantity for f in desk.fills()] == [D(20)]
        assert (desk.book.held("a", SPY), desk.book.held("b", SPY)) == (D(15), D(5))


class TestCash:
    def test_purchases_shrink_together_to_what_settled_cash_pays_for(self) -> None:
        desk = Desk("1000")
        desk.trade(TUE, ohlc(TUE, "100"), ohlc(TUE, "100", instrument=QQQ))

        caused = desk.decide(
            TUE,
            (decided("a", "1", SPY, QQQ),),
            wants(QQQ, ("a", "0.5", None)),
            wants(SPY, ("a", "0.5", None)),
        )

        assert sorted(q for _, _, q, _ in desk.submitted(caused)) == [D(4), D(4)]
        assert {line.note for line in desk.plan(caused)} == {PlanNote.CASH_LIMITED}

    @pytest.mark.parametrize(
        ("buffer", "submitted", "filled"),
        [("0", D(10), []), ("0.02", D(9), [D(9)])],
    )
    def test_the_price_buffer_leaves_room_for_a_higher_open(
        self, buffer: str, submitted: Decimal, filled: list[Decimal]
    ) -> None:
        desk = Desk("1001", rules=replace(RULES, price_buffer=D(buffer)))
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "1", None)))
        desk.trade(WED, ohlc(WED, "102"))  # opens 2% higher

        # Without a buffer, 10 shares fit at the close (1,001) but not at the open
        # (1,021), so the broker cancels the whole order. With 2%, 9 shares fit both.
        assert desk.submitted(caused)[0][2] == submitted
        assert [f.fill.quantity for f in desk.fills()] == filled

    def test_sale_proceeds_pay_for_purchases_once_they_settle(self) -> None:
        desk = Desk("1000")
        desk.trade(TUE, ohlc(TUE, "100"), ohlc(TUE, "100", instrument=QQQ))
        desk.decide(TUE, (decided("a", "1", SPY, QQQ),), wants(SPY, ("a", "0.9", None)))
        desk.trade(WED, ohlc(WED, "100"), ohlc(WED, "100", instrument=QQQ))  # 9 SPY bought

        rotate = desk.decide(WED, (decided("a", "1", SPY, QQQ),), wants(QQQ, ("a", "0.9", None)))
        desk.trade(THU, ohlc(THU, "100"), ohlc(THU, "100", instrument=QQQ))  # SPY sold
        buy = desk.decide(THU, (decided("a", "1", SPY, QQQ),), wants(QQQ, ("a", "0.9", None)))

        sides = [(o[0].split("-")[1], o[1]) for o in desk.submitted(rotate)]
        assert sides == [("SPY.ARCX", Side.SELL)]  # no cash for QQQ until the sale settles
        assert [(o[1], o[2]) for o in desk.submitted(buy)] == [(Side.BUY, D(8))]
        assert desk.broker.free_riding == ()


class TestStops:
    def entered_with_a_stop(self, low: str = "100") -> Desk:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", "95")))
        desk.trade(WED, ohlc(WED, "100", low=low))
        return desk

    def stop_orders(self, desk: Desk) -> list[tuple[str, Decimal, OrderStatus]]:
        latest: dict[str, tuple[str, Decimal, OrderStatus]] = {}
        for event in desk.recorder.events:
            if isinstance(event, OrderEvent) and event.state.order.order_type is OrderType.STOP:
                order = event.state.order
                latest[order.client_order_id] = (
                    order.client_order_id,
                    order.quantity,
                    event.state.status,
                )
        return list(latest.values())

    def test_no_stop_is_placed_before_the_entry_fills(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", "95")))

        assert [o[3] for o in desk.submitted(caused)] == [OrderType.MARKET]

    def test_the_stop_is_placed_when_the_entry_fills_for_all_the_sleeves_shares(self) -> None:
        desk = self.entered_with_a_stop()

        [fill] = desk.fills()
        assert self.stop_orders(desk) == [
            (f"{fill.fill.fill_id}-stop-a", D(50), OrderStatus.ACCEPTED)
        ]
        [order] = [
            e.state.order
            for e in desk.recorder.events
            if isinstance(e, OrderEvent)
            and e.state.order.order_type is OrderType.STOP
            and e.state.status is OrderStatus.SUBMITTED
        ]
        assert (order.time_in_force, order.stop_price) == (TimeInForce.GTC, usd("95"))
        assert desk.book.positions_of("a")[0].stop_price == usd("95")

    def test_the_stop_works_from_the_next_session_so_it_never_free_rides(self) -> None:
        desk = self.entered_with_a_stop(low="90")  # the entry session goes through the stop

        assert desk.book.held("a", SPY) == 50
        desk.trade(THU, ohlc(THU, "96", low="94"))

        assert [f.fill.side for f in desk.fills()] == [Side.BUY, Side.SELL]
        assert desk.book.positions_of("a") == ()
        assert desk.broker.free_riding == ()
        assert self.stop_orders(desk)[0][2] is OrderStatus.FILLED

    def test_a_stopped_out_position_reads_as_closed_at_the_next_decision(self) -> None:
        desk = self.entered_with_a_stop()
        desk.trade(THU, ohlc(THU, "96", low="94"))

        caused = desk.decide(THU, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", "95")))

        assert desk.plan(caused)[0].held == 0  # the strategy may enter again: a new decision
        assert [o[1] for o in desk.submitted(caused)] == [Side.BUY]

    def test_a_moved_stop_is_cancelled_and_placed_again(self) -> None:
        desk = self.entered_with_a_stop()

        caused = desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", "97")))

        [cancel] = [e for e in caused if isinstance(e, CancelRequestEvent)]
        assert cancel.client_order_id.endswith("-stop-a")
        assert desk.submitted(caused) == [
            ("20240103T210000Z-SPY.ARCX-stop-a", Side.SELL, D(50), OrderType.STOP)
        ]
        assert desk.book.positions_of("a")[0].stop_price == usd("97")

    def test_an_unchanged_stop_is_left_alone(self) -> None:
        desk = self.entered_with_a_stop()

        caused = desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", "95")))

        assert desk.submitted(caused) == []
        assert not any(isinstance(e, CancelRequestEvent) for e in caused)

    def test_an_exit_sells_and_cancels_the_stop(self) -> None:
        desk = self.entered_with_a_stop()

        caused = desk.decide(WED, (decided("a", "1", SPY),))
        desk.trade(THU, ohlc(THU, "100", low="90"))

        assert [o[1:3] for o in desk.submitted(caused)] == [(Side.SELL, D(50))]
        assert any(isinstance(e, CancelRequestEvent) for e in caused)
        assert [f.fill.side for f in desk.fills()] == [Side.BUY, Side.SELL]
        assert desk.book.stops == ()

    def test_adding_shares_replaces_the_stop_once_they_fill(self) -> None:
        desk = self.entered_with_a_stop()
        desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.7", "95")))
        desk.trade(THU, ohlc(THU, "100"))

        stops = self.stop_orders(desk)
        assert [(q, s) for _, q, s in stops] == [
            (D(50), OrderStatus.CANCELLED),
            (D(69), OrderStatus.ACCEPTED),
        ]

    def test_a_stop_only_protects_the_sleeve_that_asked_for_it(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(
            TUE,
            (decided("a", "0.5", SPY), decided("b", "0.5", SPY)),
            wants(SPY, ("a", "0.3", "95"), ("b", "0.2", None)),
        )
        desk.trade(WED, ohlc(WED, "100"))

        assert [q for _, q, _ in self.stop_orders(desk)] == [D(30)]
        assert desk.book.positions_of("b")[0].stop_price is None


class TestSettlementAtTheEndOfTheCalendar:
    def test_counts_only_cash_settled_today_when_there_is_no_next_session(self) -> None:
        short = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=TUE)
        desk = Desk("1000", calendars={"XNYS": short})
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        assert [o[2] for o in desk.submitted(caused)] == [D(5)]


class TestFailClosed:
    def test_a_decision_without_an_account_snapshot_halts(self) -> None:
        desk = Desk()

        with pytest.raises(HandlerError, match="execution") as raised:
            desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))
        assert isinstance(raised.value.__cause__, ExecutionError)
        assert "no account snapshot" in str(raised.value.__cause__)

    def test_a_market_order_still_open_at_a_decision_halts(self) -> None:
        desk = Desk()
        desk.trade(TUE, ohlc(TUE, "100"))
        desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))
        # A snapshot for the next close arrives without that session having traded.
        desk.bus.publish(AccountEvent(close_of(WED), desk.state.account), source="test")
        desk.bus.drain()

        with pytest.raises(HandlerError) as raised:
            desk.decide(WED, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))
        assert "market orders still open" in str(raised.value.__cause__)

    def test_sleeves_that_do_not_add_up_to_the_account_halt(self) -> None:
        # Shares bought outside Tyche: the account holds them, no sleeve does.
        start = (
            Account.empty()
            .deposit(usd("10000"))
            .apply_fill(fill(Side.BUY, "5", "100", trade_date=date(2023, 12, 28)))
        )
        desk = Desk(start=start)
        desk.trade(TUE, ohlc(TUE, "100"))

        with pytest.raises(HandlerError) as raised:
            desk.decide(TUE, (decided("a", "1", SPY),))
        assert "the sleeves hold 0" in str(raised.value.__cause__)

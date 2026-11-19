"""AccountState: Tyche's own view of the account, kept from the same events as the broker's."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from tests.support.costs import NO_FEES, US_COSTS, usd
from tests.support.market import SPY, close_of, dividend, session
from tests.support.recording import Recorder, TickingClock
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    Account,
    Bar,
    Currency,
    Order,
    OrderState,
    OrderType,
    PriceAdjustment,
    Side,
    Timeframe,
    TimeInForce,
)
from tyche.core.events import (
    AccountEvent,
    BarEvent,
    DistributionEvent,
    Event,
    EventBus,
    OrderEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.pipeline.execution import AccountState
from tyche.core.sim import SimBroker

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
PLAIN = replace(US_COSTS, slippage_bps=Decimal(0), regulatory_fees=NO_FEES)
TUE, WED, THU = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def daily(day: date, open_: float, close: float) -> Bar:
    return Bar(
        SPY,
        Timeframe.D1,
        close_of(day),
        open_,
        max(open_, close),
        min(open_, close),
        close,
        1_000_000.0,
        PriceAdjustment.SPLITS,
    )


class Run:
    def __init__(self) -> None:
        start = Account.empty().deposit(usd("10000"))
        self.bus = EventBus(TickingClock().now)
        self.broker = SimBroker(self.bus, start, PLAIN, {"XNYS": NYSE})
        self.state = AccountState(self.bus, start)
        self.recorder = Recorder(self.bus)

    def publish(self, *events: Event) -> None:
        for event in events:
            self.bus.publish(event, source="test")
            self.bus.drain()

    def trade(self, day: date, bar: Bar, *before_bars: Event) -> None:
        today = session(day)
        self.publish(SessionEvent(today, SessionPhase.OPEN), *before_bars, BarEvent(bar))
        self.publish(SessionEvent(today, SessionPhase.CLOSE))

    def buy(self, quantity: str) -> None:
        order = Order(
            "buy",
            SPY,
            Side.BUY,
            Decimal(quantity),
            OrderType.MARKET,
            TimeInForce.DAY,
            close_of(TUE),
            "test",
        )
        self.publish(OrderEvent(OrderState(order).submit()))

    def snapshots(self) -> list[AccountEvent]:
        return [e for e in self.recorder.events if isinstance(e, AccountEvent)]


def test_publishes_one_snapshot_at_every_session_close() -> None:
    run = Run()
    run.trade(TUE, daily(TUE, 100, 100))
    run.trade(WED, daily(WED, 100, 101))

    assert [s.as_of for s in run.snapshots()] == [close_of(TUE), close_of(WED)]


def test_follows_fills_settlement_and_closing_marks_like_the_broker() -> None:
    run = Run()
    run.trade(TUE, daily(TUE, 100, 100))
    run.buy("10")
    run.trade(WED, daily(WED, 100, 104))  # fills at the open, marked at the close
    run.trade(THU, daily(THU, 104, 103))  # the purchase settles at the open

    account = run.state.account
    assert account == run.broker.account()
    assert account.mark_of(SPY) == usd("103")
    assert account.cash(Currency.USD).settled == usd("8999")
    assert run.snapshots()[-1].account == account
    assert run.snapshots()[1].account.equity(Currency.USD) == usd("10039")


def test_credits_a_distribution_to_the_holders_at_the_previous_close() -> None:
    run = Run()
    run.trade(TUE, daily(TUE, 100, 100))
    run.buy("10")
    run.trade(WED, daily(WED, 100, 100))
    run.trade(THU, daily(THU, 100, 100), DistributionEvent(dividend(THU, "0.50")))

    assert run.state.account.distributions_received(Currency.USD) == usd("5.00")
    assert run.state.account == run.broker.account()

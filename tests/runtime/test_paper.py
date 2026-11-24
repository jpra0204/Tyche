"""``tyche paper run``'s wiring: one cycle against a fake IB Gateway (ADR-0045).

A scratch workspace trades SPY alone, buy-and-hold, under the ``unbound`` profile, so
the risk gate approves the purchase unchanged. Bars come from a scripted source; IB
Gateway is the fake the adapter's own tests use; the wall clock is a fake that the
engine and the cycle's waits move forward.
"""

from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.adapters.brokers.ibkr.fake_gateway import ACCOUNT, FakeGateway
from tests.support.market import SPY, bar
from tests.support.workspace import add_unbound_profile, keep_candidates
from tyche.adapters.brokers.ibkr import ReportedHolding, ReportedValue
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import SourceData
from tyche.adapters.kill_switch import engage
from tyche.adapters.storage import SqliteCheckpointStore, SqliteJournalStore, open_database
from tyche.config import TycheConfig, Workspace, init_workspace, load_config
from tyche.core.domain import (
    Checkpoint,
    DifferenceKind,
    Instrument,
    Kill,
    PriceAdjustment,
    ReconciliationStatus,
    Side,
)
from tyche.core.events import OrderEvent, ReconciliationEvent, RunEvent
from tyche.core.ports import AlertKind
from tyche.runtime.paper import (
    CANCEL_WAIT,
    PaperOutcome,
    PaperRunError,
    _Cycle,
    _Progress,
    run_paper,
)

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2022, 1, 3), last=date(2024, 3, 28))
TUESDAY = date(2024, 2, 6)
WEDNESDAY = date(2024, 2, 7)
EVENING = datetime(2024, 2, 6, 23, 30, tzinfo=UTC)
"""Tuesday 6 February 2024, 18:30 in New York: the session's bars are final."""
NEXT_EVENING = datetime(2024, 2, 7, 23, 30, tzinfo=UTC)
OPEN_WEDNESDAY = datetime(2024, 2, 7, 14, 30, tzinfo=UTC)
ENV = {
    "IBKR_HOST": "127.0.0.1",
    "IBKR_PORT": "4002",
    "IBKR_CLIENT_ID": "7",
    "IBKR_ACCOUNT_ID": ACCOUNT,
}


class WallClock:
    """A wall clock for tests: one second per reading; ``wait_until`` and ``sleep`` move it."""

    def __init__(self, start: datetime) -> None:
        self.at = start

    def now(self) -> datetime:
        current = self.at
        self.at += timedelta(seconds=1)
        return current

    def wait_until(self, moment: datetime) -> None:
        self.at = max(self.at, moment)

    def sleep(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


class Bars:
    """SPY closes rising 0.1% a session from early 2023, as a ``BarSource``."""

    name = "scripted"
    adjustment = PriceAdjustment.SPLITS

    def __init__(self) -> None:
        sessions = NYSE.sessions_between(date(2023, 1, 3), date(2024, 3, 1))
        self.closes = {s.day: 400 * 1.001**i for i, s in enumerate(sessions)}

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        found = tuple(
            bar(day, close, instrument=instrument)
            for day, close in self.closes.items()
            if first <= day <= last
        )
        return SourceData(bars=found)


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    home = tmp_path / "home"
    home.mkdir()
    workspace = init_workspace(home / "ws", user_home=home)
    keep_candidates(workspace.root, "SPY")
    profile = add_unbound_profile(workspace.root)
    return load_config(Workspace(workspace.root), profile)


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.values = [cash("10000.00")]
    return gateway


def cash(*amounts: str, on: date = TUESDAY) -> ReportedValue:
    """``SettledCashByDate`` in USD: the first amount now, each later one a session on."""
    days = [on, *(s.day for s in NYSE.sessions_between(on + timedelta(1), on + timedelta(10)))]
    text = ";".join(f"{d:%Y%m%d}:{a}" for d, a in zip(days, amounts, strict=False))
    return ReportedValue(ACCOUNT, "SettledCashByDate", text, "USD")


def paper(config: TycheConfig, gateway: FakeGateway, at: datetime = EVENING) -> PaperOutcome:
    clock = WallClock(at)
    return run_paper(
        config,
        environ=ENV,
        code_version="0.0.0+test",
        clock=clock,
        client=gateway,
        source=Bars(),
        sleep=clock.sleep,
    )


def journal(config: TycheConfig, run_id: str) -> list[object]:
    with closing(open_database(config.workspace.state_database)) as connection:
        return [e.event for e in SqliteJournalStore(connection).read(run_id)]


def latest(config: TycheConfig) -> Checkpoint | None:
    with closing(open_database(config.workspace.state_database)) as connection:
        return SqliteCheckpointStore(connection).latest()


def buy_and_fill(config: TycheConfig, gateway: FakeGateway) -> str:
    """The first run buys SPY; it fills at Wednesday's open. Returns the order id."""
    first = paper(config, gateway)
    assert first.completed, first.failure
    (ticket,) = gateway.placed
    price = Decimal(str(Bars().closes[WEDNESDAY])).quantize(Decimal("0.01"))
    gateway.execute(ticket.order_ref, str(ticket.quantity), str(price), OPEN_WEDNESDAY)
    gateway.set_status(ticket.order_ref, "Filled")
    cost = Decimal(ticket.quantity) * price + Decimal("1.00")
    left = Decimal("10000.00") - cost
    gateway.values = [cash(str(left), on=WEDNESDAY)]
    gateway.portfolio = [
        ReportedHolding(ACCOUNT, "SPY", "USD", Decimal(ticket.quantity), cost, Decimal("431"))
    ]
    return ticket.order_ref


class TestFirstRun:
    def test_starts_from_ibkrs_cash_and_buys_for_the_next_open(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        outcome = paper(config, gateway)

        assert outcome.completed, outcome.failure
        assert outcome.first_run
        assert outcome.check_run == "paper-20240206T233000Z-check"
        assert outcome.decision_run == "paper-20240206T233000Z"
        assert outcome.traded is not None
        assert outcome.traded.day == TUESDAY
        (ticket,) = gateway.placed
        assert (ticket.action, ticket.order_type, ticket.time_in_force) == ("BUY", "MKT", "OPG")
        assert outcome.startup is not None
        assert outcome.startup.status is ReconciliationStatus.MATCH
        assert outcome.after is not None
        assert outcome.after.status is ReconciliationStatus.MATCH
        saved = latest(config)
        assert saved is not None
        assert saved.run_id == outcome.decision_run
        assert [o.state.order.side for o in saved.execution.orders] == [Side.BUY]

    def test_records_two_runs_each_with_its_reconciliation(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        outcome = paper(config, gateway)

        for run_id in (outcome.check_run, outcome.decision_run):
            assert run_id is not None
            events = journal(config, run_id)
            assert isinstance(events[0], RunEvent)
            assert sum(isinstance(e, ReconciliationEvent) for e in events) == 1
        decided = journal(config, str(outcome.decision_run))
        assert any(isinstance(e, OrderEvent) for e in decided)

    def test_refuses_an_account_holding_a_position(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        gateway.portfolio = [
            ReportedHolding(ACCOUNT, "SPY", "USD", Decimal(3), Decimal(1200), Decimal(400))
        ]

        outcome = paper(config, gateway)

        assert not outcome.completed
        assert outcome.failure is not None
        assert "holding nothing but cash" in outcome.failure
        assert "3 SPY@ARCX" in outcome.failure
        assert gateway.placed == []
        assert latest(config) is None
        assert [a.kind for a in outcome.alerts] == [AlertKind.RUN_FAILED]

    def test_refuses_an_account_with_no_usd(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        gateway.values = [ReportedValue(ACCOUNT, "SettledCashByDate", "20240206:5000", "CAD")]

        outcome = paper(config, gateway)

        assert outcome.failure is not None
        assert "no USD cash" in outcome.failure
        assert latest(config) is None

    def test_needs_the_gateway_connection_in_env(self, config: TycheConfig) -> None:
        with pytest.raises(PaperRunError, match="IBKR_ACCOUNT_ID"):
            run_paper(
                config,
                environ={k: v for k, v in ENV.items() if k != "IBKR_ACCOUNT_ID"},
                code_version="0.0.0+test",
                clock=WallClock(EVENING),
                client=FakeGateway(),
                source=Bars(),
            )


class TestLaterRuns:
    def test_a_second_run_the_same_evening_only_checks(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        paper(config, gateway)

        again = paper(config, gateway, EVENING + timedelta(hours=1))

        assert again.completed, again.failure
        assert not again.first_run
        assert again.decision_run is None
        assert len(gateway.placed) == 1
        saved = latest(config)
        assert saved is not None
        assert saved.run_id == again.check_run

    def test_the_next_evening_reads_the_fill_and_holds(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        order_id = buy_and_fill(config, gateway)

        outcome = paper(config, gateway, NEXT_EVENING)

        assert outcome.completed, outcome.failure
        assert outcome.startup is not None
        assert outcome.startup.status is not ReconciliationStatus.MISMATCH
        assert outcome.traded is not None
        assert outcome.traded.day == WEDNESDAY
        saved = latest(config)
        assert saved is not None
        (position,) = saved.account.positions
        assert position.instrument == SPY
        assert saved.execution.orders == ()
        assert [t.order_ref for t in gateway.placed] == [order_id]  # held, nothing new

    def test_a_market_order_still_working_next_evening_halts(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        paper(config, gateway)
        (ticket,) = gateway.placed
        gateway.set_status(ticket.order_ref, "Submitted")  # IBKR still lists it working

        outcome = paper(config, gateway, NEXT_EVENING)

        assert outcome.completed, outcome.failure
        assert outcome.startup is not None
        assert [d.kind for d in outcome.startup.differences] == [DifferenceKind.STALE_ORDER]
        assert len(gateway.placed) == 1  # the decision sent nothing
        saved = latest(config)
        assert saved is not None
        assert saved.reconciliation.halt is not None
        assert AlertKind.RECONCILIATION in [a.kind for a in outcome.alerts]

    def test_a_halt_from_an_earlier_run_is_alerted_at_startup(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        paper(config, gateway)
        (ticket,) = gateway.placed
        gateway.set_status(ticket.order_ref, "Submitted")
        paper(config, gateway, NEXT_EVENING)
        gateway.set_status(ticket.order_ref, "Cancelled")  # Pablo cancels it in the app

        outcome = paper(config, gateway, NEXT_EVENING + timedelta(hours=1))

        assert outcome.startup is not None
        assert outcome.startup.status is not ReconciliationStatus.MISMATCH
        assert [a.kind for a in outcome.alerts] == [AlertKind.STOPPED]


class TestKillSwitch:
    def test_a_flatten_sells_at_the_next_open(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        buy_and_fill(config, gateway)
        engage(config.workspace.kill_file, Kill("test", flatten=True, engaged_at=EVENING))

        outcome = paper(config, gateway, NEXT_EVENING)

        assert outcome.completed, outcome.failure
        sale = gateway.placed[-1]
        assert (sale.action, sale.order_type, sale.time_in_force) == ("SELL", "MKT", "OPG")
        assert AlertKind.KILL_SWITCH in [a.kind for a in outcome.alerts]

    def test_without_flatten_nothing_is_sent(
        self, config: TycheConfig, gateway: FakeGateway
    ) -> None:
        buy_and_fill(config, gateway)
        engage(config.workspace.kill_file, Kill("test", flatten=False, engaged_at=EVENING))

        outcome = paper(config, gateway, NEXT_EVENING)

        assert outcome.completed, outcome.failure
        assert len(gateway.placed) == 1


class TestWaitingForCancellations:
    """``_read``: a sale goes out once its stop's cancellation is confirmed (ADR-0045)."""

    class Broker:
        """Holds one sale until IBKR has confirmed the stop's cancellation ``after`` reads."""

        def __init__(self, after: int | None) -> None:
            self.after = after
            self.reads = 0
            self.held: tuple[str, ...] = ("sell-spy",)
            self.rejected: list[str] = []

        def sync(self) -> object:
            self.reads += 1
            return type("Report", (), {"lost": (), "foreign_executions": 0})()

        def release(self) -> tuple[str, ...]:
            if self.after is not None and self.reads > self.after:
                self.held = ()
            return self.held

        def reject_held(self, reason: str) -> tuple[str, ...]:
            self.rejected.extend(self.held)
            rejected, self.held = self.held, ()
            return rejected

    def read(self, broker: TestWaitingForCancellations.Broker) -> tuple[_Progress, WallClock]:
        clock = WallClock(EVENING)
        cycle = object.__new__(_Cycle)
        cycle._clock = clock
        cycle._sleep = clock.sleep
        progress = _Progress(check_run="paper-test-check")
        cycle._read(broker, progress)  # type: ignore[arg-type]
        return progress, clock

    def test_the_sale_goes_once_the_cancellation_is_confirmed(self) -> None:
        broker = self.Broker(after=3)

        progress, _ = self.read(broker)

        assert progress.not_sent == []
        assert broker.rejected == []
        assert broker.reads == 5  # the first read, three more while waiting, one at the end

    def test_a_sale_still_waiting_after_a_minute_is_rejected_unsent(self) -> None:
        broker = self.Broker(after=None)

        progress, clock = self.read(broker)

        assert progress.not_sent == ["sell-spy"]
        assert clock.at - EVENING >= CANCEL_WAIT
        assert clock.at - EVENING < CANCEL_WAIT + timedelta(minutes=1)

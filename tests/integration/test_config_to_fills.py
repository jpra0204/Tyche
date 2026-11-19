"""From the workspace config to fills, on the real New York calendar (Phase 1, PR 14).

The whole trading path runs: replay, universe, screening, signals, portfolio, the
pass-through risk gate, execution, the simulated broker and Tyche's own account view.

* Two buy-and-hold sleeves (0.6 SPY, 0.4 QQQ) buy once and then hold: the rebalance
  band keeps them from trading a share at a time, a data gap on QQQ is a keep, not a
  sale, and the strategies see their own positions.
* A strategy with a stop gets its stop after the entry fills, is stopped out by a fall,
  enters again at the next decision, and never free-rides.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from tests.support.market import QQQ, SPY, bar, close_of
from tests.support.workspace import BACKTEST
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.config import TycheConfig, init_workspace, load_config
from tyche.core.domain import (
    Account,
    Bar,
    BarHistory,
    Currency,
    Money,
    OrderStatus,
    OrderType,
    PriceAdjustment,
    Side,
    Target,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.engine import Engine
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    EventBus,
    FillEvent,
    OrderEvent,
    RunMode,
    SignalEvent,
)
from tyche.core.pipeline.execution import AccountState, ExecutionStage, SleeveBook
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.portfolio import PortfolioStage
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage, Strategy, StrategyContext
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.risk import PassThroughGate
from tyche.core.sim import HistoricalReplay, SimBroker, SimClock
from tyche.runtime.strategies import build_strategies

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 31)
GAP_DAY = date(2024, 1, 17)
DEPOSIT = Money.of("10000", Currency.USD)

HOLD_QQQ = """plugin = "buy_and_hold"
[parameters]
symbol = "QQQ"
exchange = "XNAS"
asset_class = "etf"
"""


@dataclass
class Run:
    journal: InMemoryJournal
    broker: SimBroker
    state: AccountState
    book: SleeveBook


def configured(tmp_path: Path, strategies: str) -> TycheConfig:
    home = tmp_path / "home"
    home.mkdir()
    workspace = init_workspace(home / "ws", user_home=home)
    workspace.tyche_config.write_text(
        f'schema_version = 1\nmarket_profile = "US"\n{BACKTEST}[strategies]\n{strategies}\n'
    )
    (workspace.strategies_dir / "hold_qqq.toml").write_text(HOLD_QQQ)
    return load_config(workspace)


def run(
    config: TycheConfig,
    histories: list[BarHistory],
    strategies: Sequence[Strategy],
    budgets: Mapping[str, Decimal],
) -> Run:
    profile = config.market_profile
    profile = replace(profile, universe=replace(profile.universe, liquidity_sessions=5))
    calendars = {"XNYS": NYSE}
    replay = HistoricalReplay(histories, calendars, FIRST, LAST)
    assert replay.start is not None
    clock = SimClock(replay.start)
    bus = EventBus(clock.now)
    start = Account.empty().deposit(DEPOSIT)

    book = SleeveBook()
    UniverseStage(bus, profile)
    ScreeningStage(bus, DollarVolumeScreen())
    SignalsStage(bus, strategies, positions=book)
    PortfolioStage(bus, budgets)
    PassThroughGate(bus)
    state = AccountState(bus, start)
    ExecutionStage(bus, book, config.costs, calendars, profile.execution)
    broker = SimBroker(bus, start, config.costs, calendars)
    journal = InMemoryJournal(bus)

    result = Engine(bus, clock, run_id="it", mode=RunMode.BACKTEST, code_version="test").run(replay)
    assert result.completed, result.failure
    return Run(journal, broker, state, book)


def histories_for(bars: dict[str, list[Bar]]) -> list[BarHistory]:
    sessions = list(NYSE.sessions_between(FIRST, LAST))
    instruments = {"SPY": SPY, "QQQ": QQQ}
    return [
        audit_daily_bars(instruments[s], b, sessions, adjustment=PriceAdjustment.SPLITS)
        for s, b in bars.items()
    ]


class TestBuyAndHoldSleeves:
    def run(self, tmp_path: Path) -> Run:
        config = configured(tmp_path, 'buy_and_hold = "0.6"\nhold_qqq = "0.4"')
        sessions = list(NYSE.sessions_between(FIRST, LAST))
        # Prices drift apart a little every day: SPY up, QQQ down.
        spy = [bar(s.day, 470.0 + i * 0.5, instrument=SPY) for i, s in enumerate(sessions)]
        qqq = [
            bar(s.day, 400.0 - i * 0.5, instrument=QQQ)
            for i, s in enumerate(sessions)
            if s.day != GAP_DAY
        ]
        built = build_strategies(config)
        histories = histories_for({"SPY": spy, "QQQ": qqq})
        return run(config, histories, built.strategies, built.budgets)

    def test_each_sleeve_buys_once_and_then_holds(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        fills = [e.event.fill for e in result.journal.of_type(FillEvent)]
        assert sorted((f.instrument.symbol, f.side) for f in fills) == [
            ("QQQ", Side.BUY),
            ("SPY", Side.BUY),
        ]
        assert {f.trade_date for f in fills} == {fills[0].trade_date}

    def test_the_account_ends_about_fully_invested_in_its_budgets(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        account = result.state.account
        equity = account.equity(Currency.USD)
        spy, qqq = account.position(SPY), account.position(QQQ)
        assert spy is not None
        assert qqq is not None
        spy_weight = account.mark_of(SPY) * spy.quantity / equity  # type: ignore[operator]
        qqq_weight = account.mark_of(QQQ) * qqq.quantity / equity  # type: ignore[operator]
        assert Decimal("0.54") < spy_weight < Decimal("0.66")
        assert Decimal("0.36") < qqq_weight < Decimal("0.44")
        assert account.cash(Currency.USD).settled.is_positive

    def test_tyche_and_the_broker_agree_on_the_account(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        assert result.state.account == result.broker.account()
        last = result.journal.of_type(AccountEvent)[-1].event
        assert last.as_of == close_of(LAST)
        assert last.account == result.broker.account()

    def test_strategies_see_their_own_positions(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        reasons = [
            t.reason
            for e in result.journal.of_type(SignalEvent)
            if e.event.strategy_id == "hold_qqq"
            for t in e.event.targets
        ]
        assert reasons[0] == "buy and hold QQQ@XNAS: enter"
        assert reasons[-1].startswith("buy and hold QQQ@XNAS: hold since 2024-01-")
        [position] = result.book.positions_of("hold_qqq")
        assert position.instrument == QQQ

    def test_every_order_comes_from_an_approved_portfolio(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        for envelope in result.journal.of_type(OrderEvent):
            if envelope.event.state.status is not OrderStatus.SUBMITTED:
                continue
            kinds = {type(c.event) for c in result.journal.causes_of(envelope)}
            assert ApprovedPortfolioEvent in kinds

    def test_no_free_riding(self, tmp_path: Path) -> None:
        assert self.run(tmp_path).broker.free_riding == ()


@dataclass
class StopTrader:
    """Holds SPY with its whole budget and a stop 5% below the last close."""

    strategy_id: str = "stopper"
    version: str = "1"
    timeframe: Timeframe = Timeframe.D1
    lookback: int = 1

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        if SPY not in context.instruments:
            return ()
        close = Decimal(repr(context.history.bars(SPY, Timeframe.D1)[-1].close))
        stop = Money((close * Decimal("0.95")).quantize(Decimal("0.01")), Currency.USD)
        return (Target(SPY, Decimal(1), "hold with a stop", stop),)


class TestAStopStrategy:
    FALL = date(2024, 1, 22)

    def run(self, tmp_path: Path) -> Run:
        # The workspace gives the profile and the costs; the strategy is wired by hand.
        config = configured(tmp_path, 'buy_and_hold = "1.0"')
        sessions = list(NYSE.sessions_between(FIRST, LAST))
        spy: list[Bar] = []
        for s in sessions:
            b = bar(s.day, 100.0, instrument=SPY)
            if s.day == self.FALL:  # opens at 99, falls to 90, closes at 92
                b = replace(b, open=99.0, high=99.0, low=90.0, close=92.0)
            spy.append(b)
        histories = histories_for({"SPY": spy})
        return run(config, histories, [StopTrader()], {"stopper": Decimal(1)})

    def stop_orders(self, result: Run) -> list[OrderEvent]:
        return [
            e.event
            for e in result.journal.of_type(OrderEvent)
            if e.event.state.order.order_type is OrderType.STOP
        ]

    def test_the_stop_is_placed_when_the_entry_fills(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        first_fill = result.journal.of_type(FillEvent)[0]
        first_stop = next(
            e
            for e in result.journal.of_type(OrderEvent)
            if e.event.state.order.order_type is OrderType.STOP
        )
        assert first_stop.caused_by == first_fill.seq

    def test_the_fall_stops_the_position_out_and_the_strategy_enters_again(
        self, tmp_path: Path
    ) -> None:
        result = self.run(tmp_path)

        fills = [e.event.fill for e in result.journal.of_type(FillEvent)]
        sells = [f for f in fills if f.side is Side.SELL]
        # The stop at 95 (5% below the last close of 100), less 5 bp of slippage.
        assert [(f.trade_date, f.price) for f in sells] == [
            (self.FALL, Money.of("94.9525", Currency.USD))
        ]
        assert fills[-1].side is Side.BUY  # re-entered after the stop-out
        assert fills[-1].trade_date > self.FALL
        assert result.book.held("stopper", SPY) > 0

    def test_never_free_rides(self, tmp_path: Path) -> None:
        assert self.run(tmp_path).broker.free_riding == ()

    def test_tyche_and_the_broker_agree_on_the_account(self, tmp_path: Path) -> None:
        result = self.run(tmp_path)

        assert result.state.account == result.broker.account()

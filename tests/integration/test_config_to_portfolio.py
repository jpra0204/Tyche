"""From the workspace config to the proposed portfolio, on the real New York calendar.

A workspace configures two strategies, buy-and-hold SPY with 0.6 of the account and
buy-and-hold QQQ with 0.4. The run goes replay, universe, screening, signals and
portfolio. QQQ misses a session: its sleeve stops deciding on QQQ for a while, which
the portfolio says as "keep", not as a sale.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from tests.support.market import QQQ, SPY, bar
from tests.support.profiles import US_PROFILE
from tests.support.workspace import BACKTEST
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.config import init_workspace, load_config
from tyche.core.domain import PriceAdjustment, SleeveStatus, audit_daily_bars
from tyche.core.engine import Engine
from tyche.core.events import EventBus, RunMode, TargetPortfolioEvent
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.portfolio import PortfolioStage
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.sim import HistoricalReplay, SimClock
from tyche.runtime.strategies import build_strategies

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 31)
GAP_DAY = date(2024, 1, 17)

HOLD_QQQ = """plugin = "buy_and_hold"
[parameters]
symbol = "QQQ"
exchange = "XNAS"
asset_class = "etf"
"""


def run(tmp_path: Path) -> InMemoryJournal:
    home = tmp_path / "home"
    home.mkdir()
    workspace = init_workspace(home / "ws", user_home=home)
    workspace.tyche_config.write_text(
        'schema_version = 1\nmarket_profile = "US"\n'
        + BACKTEST
        + '[strategies]\nbuy_and_hold = "0.6"\nhold_qqq = "0.4"\n'
    )
    (workspace.strategies_dir / "hold_qqq.toml").write_text(HOLD_QQQ)
    configured = build_strategies(load_config(workspace))

    sessions = list(NYSE.sessions_between(FIRST, LAST))
    spy = [bar(s.day, 470.0, instrument=SPY) for s in sessions]
    qqq = [bar(s.day, 400.0, instrument=QQQ) for s in sessions if s.day != GAP_DAY]
    histories = [
        audit_daily_bars(SPY, spy, sessions, adjustment=PriceAdjustment.SPLITS),
        audit_daily_bars(QQQ, qqq, sessions, adjustment=PriceAdjustment.SPLITS),
    ]
    profile = replace(US_PROFILE, universe=replace(US_PROFILE.universe, liquidity_sessions=5))
    replay = HistoricalReplay(histories, {"XNYS": NYSE}, FIRST, LAST)
    assert replay.start is not None
    clock = SimClock(replay.start)
    bus = EventBus(clock.now)
    UniverseStage(bus, profile)
    ScreeningStage(bus, DollarVolumeScreen())
    SignalsStage(bus, configured.strategies)
    PortfolioStage(bus, configured.budgets)
    journal = InMemoryJournal(bus)
    result = Engine(bus, clock, run_id="it", mode=RunMode.BACKTEST, code_version="test").run(replay)
    assert result.completed, result.failure
    return journal


def portfolios(journal: InMemoryJournal) -> dict[date, TargetPortfolioEvent]:
    return {e.event.as_of.date(): e.event for e in journal.of_type(TargetPortfolioEvent)}


def test_one_proposed_portfolio_per_session(tmp_path: Path) -> None:
    by_day = portfolios(run(tmp_path))

    assert list(by_day) == [s.day for s in NYSE.sessions_between(FIRST, LAST)]


def test_both_sleeves_invest_their_budgets_once_eligible(tmp_path: Path) -> None:
    portfolio = portfolios(run(tmp_path))[date(2024, 1, 16)]

    assert [(t.instrument, t.weight) for t in portfolio.targets] == [
        (QQQ, Decimal("0.4")),
        (SPY, Decimal("0.6")),
    ]
    assert sum(t.weight for t in portfolio.targets) == 1


def test_a_data_gap_keeps_the_position_instead_of_selling_it(tmp_path: Path) -> None:
    portfolio = portfolios(run(tmp_path))[GAP_DAY]

    sleeve = portfolio.sleeve("hold_qqq")
    assert sleeve.status is SleeveStatus.DECIDED
    assert QQQ not in sleeve.decided_on  # so whatever it holds of QQQ is kept
    assert [t.instrument for t in portfolio.targets] == [SPY]

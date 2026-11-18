"""Replay, universe, screening and signals together on the real New York calendar.

Checks the strategy contract against the replay's real order of events: the warm-up
seeds windows without lookahead, each strategy is shown exactly its lookback, an
instrument short of history is flagged rather than given a partial window, and a data
gap makes buy-and-hold go quiet instead of selling.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from tests.support.market import QQQ, SPY, bar
from tests.support.profiles import US_PROFILE
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    Bar,
    BarHistory,
    Instrument,
    PriceAdjustment,
    Session,
    Target,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.engine import Engine
from tyche.core.events import EventBus, RunMode, SignalEvent, SignalsReadyEvent
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage, StrategyContext
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.sim import HistoricalReplay, SimClock
from tyche.strategies import BuyAndHold

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 10, 1), last=date(2024, 3, 31))
WARM_FIRST, FIRST, LAST = date(2023, 11, 1), date(2024, 1, 2), date(2024, 1, 31)
GAP_DAY = date(2024, 1, 17)
LOOKBACK = 30


@dataclass
class Watcher:
    """Records what it is shown; holds nothing."""

    strategy_id: str = "watcher"
    version: str = "1"
    timeframe: Timeframe = Timeframe.D1
    lookback: int = LOOKBACK
    seen: list[StrategyContext] = field(default_factory=list)

    def decide(self, context: StrategyContext) -> tuple[Target, ...]:
        self.seen.append(context)
        return ()


def bars_for(instrument: Instrument, sessions: list[Session]) -> list[Bar]:
    return [bar(s.day, 50.0 + i * 0.1, instrument=instrument) for i, s in enumerate(sessions)]


def run() -> tuple[InMemoryJournal, Watcher]:
    warm = list(NYSE.sessions_between(WARM_FIRST, FIRST))[:-1]
    sessions = list(NYSE.sessions_between(FIRST, LAST))
    every = warm + sessions
    # SPY has the warm-up history; QQQ is new, with bars from FIRST only, and misses GAP_DAY.
    spy = audit_daily_bars(SPY, bars_for(SPY, every), every, adjustment=PriceAdjustment.SPLITS)
    qqq_bars = [b for b in bars_for(QQQ, sessions) if b.timestamp.date() != GAP_DAY]
    qqq = audit_daily_bars(QQQ, qqq_bars, sessions, adjustment=PriceAdjustment.SPLITS)
    profile = replace(US_PROFILE, universe=replace(US_PROFILE.universe, liquidity_sessions=5))

    replay = HistoricalReplay([spy, qqq], {"XNYS": NYSE}, FIRST, LAST)
    assert replay.start is not None
    clock = SimClock(replay.start)
    bus = EventBus(clock.now)
    UniverseStage(bus, profile)
    ScreeningStage(bus, DollarVolumeScreen())
    watcher = Watcher()
    signals = SignalsStage(bus, [BuyAndHold(QQQ, strategy_id="hold_qqq"), watcher])
    journal = InMemoryJournal(bus)
    # The one warm-up path: everything known before the first event, nothing after.
    signals.warm_up(
        [BarHistory(SPY, spy.bars), BarHistory(QQQ, qqq.bars)], through=warm[-1].closes_at
    )
    result = Engine(bus, clock, run_id="it", mode=RunMode.BACKTEST, code_version="test").run(replay)
    assert result.completed, result.failure
    return journal, watcher


def test_every_cycle_ends_with_every_strategy_reporting() -> None:
    journal, _ = run()

    readies = journal.of_type(SignalsReadyEvent)
    assert len(readies) == len(list(NYSE.sessions_between(FIRST, LAST)))
    assert all(r.event.reported == ("hold_qqq", "watcher") and not r.event.failed for r in readies)


def test_the_warm_up_gives_full_windows_from_the_first_eligible_day() -> None:
    _, watcher = run()

    first = next(c for c in watcher.seen if SPY in c.instruments)
    bars = first.history.bars(SPY, Timeframe.D1)
    assert len(bars) == LOOKBACK
    assert bars[-1].timestamp == first.as_of
    assert all(
        b.timestamp <= c.as_of
        for c in watcher.seen
        for i in c.instruments
        for b in c.history.bars(i, Timeframe.D1)
    )


def test_a_new_instrument_is_flagged_until_its_window_is_full() -> None:
    _, watcher = run()

    flagged = [c for c in watcher.seen if any(w.instrument == QQQ for w in c.warming_up)]
    assert flagged
    assert all(QQQ not in c.instruments for c in flagged)
    assert all(w.bars_held < LOOKBACK for c in flagged for w in c.warming_up)


def test_buy_and_hold_goes_quiet_on_a_data_gap_instead_of_selling() -> None:
    journal, _ = run()

    by_day = {
        e.event.as_of.date(): e.event.targets
        for e in journal.of_type(SignalEvent)
        if e.event.strategy_id == "hold_qqq"
    }
    assert by_day[date(2024, 1, 16)] == (Target(QQQ, Decimal(1), "buy and hold QQQ@XNAS: enter"),)
    assert by_day[GAP_DAY] == ()

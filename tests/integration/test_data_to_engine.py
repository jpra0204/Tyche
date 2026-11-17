"""Everything built so far, end to end: source, cache, audit, replay, engine, journal.

Two properties a backtest must have, checked on the real New York calendar:

* no lookahead: no subscriber ever sees a bar before the clock reaches its close;
* determinism: the same inputs give the same journal, event for event.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.market import JANUARY_2024, SPY
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import CachedDataProvider, ParquetBarCache, YFinanceSource
from tyche.core.domain import Instrument
from tyche.core.engine import Engine, RunResult
from tyche.core.events import (
    BarEvent,
    DataQualityEvent,
    DataReadyEvent,
    Envelope,
    Event,
    EventBus,
    RunMode,
)
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.ports import Calendar
from tyche.core.sim import HistoricalReplay, SimClock

QQQ = Instrument("QQQ", "XNAS", SPY.currency, "XNYS", SPY.asset_class)
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 16)


class LookaheadGuard:
    """Fails the run if any event shows a bar whose close the clock has not reached."""

    def __init__(self, bus: EventBus, clock: SimClock) -> None:
        self.clock = clock
        self.latest_bar: datetime | None = None
        self.checked = 0
        bus.subscribe(Event, self.check, name="lookahead-guard")

    def check(self, envelope: Envelope[Event]) -> None:
        now = self.clock.now()
        if isinstance(envelope.event, BarEvent):
            stamp = envelope.event.bar.timestamp
            assert stamp <= now, f"bar stamped {stamp} seen at {now}"
            self.latest_bar = max(stamp, self.latest_bar or stamp)
        if isinstance(envelope.event, DataReadyEvent):
            assert envelope.event.as_of <= now
            assert self.latest_bar is None or self.latest_bar <= envelope.event.as_of
        self.checked += 1


def run_backtest(tmp_path: Path) -> tuple[InMemoryJournal, RunResult, LookaheadGuard]:
    nyse: Calendar = ExchangeCalendarsCalendar(
        "XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31)
    )
    calendars = {"XNYS": nyse}
    rows = [row(day, 100.0 + i) for i, day in enumerate(JANUARY_2024) if day != date(2024, 1, 9)]
    source = YFinanceSource(calendars, fetch=FakeFetch(rows, list(rows)))
    provider = CachedDataProvider(
        source,
        ParquetBarCache(tmp_path / "data", source=source.name),
        calendars,
        SimClock(datetime(2024, 1, 20, tzinfo=UTC)),  # fetching happens after the fact
    )
    histories = [provider.daily_bars(SPY, FIRST, LAST), provider.daily_bars(QQQ, FIRST, LAST)]

    replay = HistoricalReplay(histories, calendars, FIRST, LAST)
    assert replay.start is not None
    clock = SimClock(replay.start)
    bus = EventBus(clock.now)
    guard = LookaheadGuard(bus, clock)
    journal = InMemoryJournal(bus)
    result = Engine(bus, clock, run_id="it", mode=RunMode.BACKTEST, code_version="test").run(replay)
    return journal, result, guard


def test_a_replayed_backtest_runs_to_completion(tmp_path: Path) -> None:
    journal, result, guard = run_backtest(tmp_path)

    assert result.completed, result.failure
    assert len(journal.of_type(DataReadyEvent)) == len(JANUARY_2024)
    assert len(journal.of_type(BarEvent)) == 2 * (len(JANUARY_2024) - 1)
    assert guard.checked == len(journal)


def test_a_missing_session_reaches_the_journal_with_its_cycle(tmp_path: Path) -> None:
    journal, _, _ = run_backtest(tmp_path)

    issues = journal.of_type(DataQualityEvent)
    [ready] = [
        e for e in journal.of_type(DataReadyEvent) if e.event.as_of.date() == date(2024, 1, 9)
    ]

    assert {(e.event.issue.instrument.symbol, e.event.issue.session_day) for e in issues} == {
        ("SPY", date(2024, 1, 9)),
        ("QQQ", date(2024, 1, 9)),
    }
    assert ready.event.delivered == ()
    assert ready.event.missing == (SPY, QQQ)
    assert ready.cycle_id == "XNYS:2024-01-09:1d"


def test_the_same_backtest_twice_gives_the_same_journal(tmp_path: Path) -> None:
    first, _, _ = run_backtest(tmp_path / "one")
    second, _, _ = run_backtest(tmp_path / "two")

    assert first.entries == second.entries

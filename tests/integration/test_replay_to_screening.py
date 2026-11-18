"""Replay, universe and screening together on the real New York calendar.

Checks what the unit tests cannot: that the stages work with the replay's real order
of events, that the warm-up and a data gap play out session by session, and that each
ranking can be traced back to the data that caused it.
"""

from dataclasses import replace
from datetime import date

from tests.support.market import QQQ, SPY
from tests.support.profiles import US_PROFILE
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    AssetClass,
    Bar,
    Currency,
    ExclusionReason,
    Instrument,
    PriceAdjustment,
    Session,
    Timeframe,
    audit_daily_bars,
)
from tyche.core.engine import Engine
from tyche.core.events import DataReadyEvent, EventBus, RunMode, ScreeningEvent, UniverseEvent
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.sim import HistoricalReplay, SimClock

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
FIRST, LAST = date(2024, 1, 2), date(2024, 2, 29)
THIN = Instrument("THIN", "XNAS", Currency.USD, "XNYS", AssetClass.STOCK)
GAP_DAY = date(2024, 2, 7)


def bars_for(instrument: Instrument, sessions: list[Session], volume: float) -> list[Bar]:
    return [
        Bar(
            instrument,
            Timeframe.D1,
            s.closes_at,
            50.0,
            51.0,
            49.0,
            50.0,
            volume,
            PriceAdjustment.SPLITS,
        )
        for s in sessions
    ]


def run() -> InMemoryJournal:
    sessions = list(NYSE.sessions_between(FIRST, LAST))
    profile = replace(US_PROFILE, universe=replace(US_PROFILE.universe, liquidity_sessions=20))
    # 50 x 1,000,000 = 50M a day for SPY and QQQ; THIN trades 100k dollars a day.
    spy_bars = bars_for(SPY, sessions, 1_000_000.0)
    qqq_bars = [b for b in bars_for(QQQ, sessions, 2_000_000.0) if b.timestamp.date() != GAP_DAY]
    histories = [
        audit_daily_bars(SPY, spy_bars, sessions, adjustment=PriceAdjustment.SPLITS),
        audit_daily_bars(QQQ, qqq_bars, sessions, adjustment=PriceAdjustment.SPLITS),
        audit_daily_bars(
            THIN, bars_for(THIN, sessions, 2_000.0), sessions, adjustment=PriceAdjustment.SPLITS
        ),
    ]
    replay = HistoricalReplay(histories, {"XNYS": NYSE}, FIRST, LAST)
    assert replay.start is not None
    clock = SimClock(replay.start)
    bus = EventBus(clock.now)
    UniverseStage(bus, profile)
    ScreeningStage(bus, DollarVolumeScreen())
    journal = InMemoryJournal(bus)
    result = Engine(bus, clock, run_id="it", mode=RunMode.BACKTEST, code_version="test").run(replay)
    assert result.completed, result.failure
    return journal


def test_one_universe_and_one_ranking_per_session() -> None:
    journal = run()
    sessions = list(NYSE.sessions_between(FIRST, LAST))

    universes = journal.of_type(UniverseEvent)
    rankings = journal.of_type(ScreeningEvent)
    assert len(universes) == len(rankings) == len(sessions) == 41
    assert [u.event.as_of for u in universes] == [s.closes_at for s in sessions]


def test_nothing_is_eligible_until_twenty_bars_have_arrived() -> None:
    universes = [u.event for u in run().of_type(UniverseEvent)]

    for event in universes[:19]:
        assert event.eligible == ()
        assert {e.reason for e in event.excluded} == {ExclusionReason.INSUFFICIENT_HISTORY}
    assert [m.instrument for m in universes[19].eligible] == [SPY, QQQ]


def test_a_thin_stock_is_excluded_as_illiquid_once_its_history_is_long_enough() -> None:
    universes = [u.event for u in run().of_type(UniverseEvent)]

    reasons = {e.instrument: e.reason for e in universes[19].excluded}
    assert reasons == {THIN: ExclusionReason.ILLIQUID}


def test_a_missing_bar_keeps_an_instrument_out_then_it_returns() -> None:
    by_day = {u.event.as_of.date(): u.event for u in run().of_type(UniverseEvent)}
    days = sorted(by_day)
    gap = days.index(GAP_DAY)

    def reason(day: date) -> ExclusionReason | None:
        found = [e.reason for e in by_day[day].excluded if e.instrument == QQQ]
        return found[0] if found else None

    assert reason(days[gap - 1]) is None
    assert reason(days[gap]) is ExclusionReason.NO_BAR
    assert [reason(d) for d in days[gap + 1 : gap + 5]] == [ExclusionReason.DATA_ISSUE] * 4
    assert reason(days[gap + 5]) is None


def test_the_ranking_puts_the_most_traded_first_and_traces_back_to_the_data() -> None:
    journal = run()
    last = journal.of_type(ScreeningEvent)[-1]

    assert [s.instrument for s in last.event.ranked] == [QQQ, SPY]
    chain = [type(e.event) for e in journal.causes_of(last)]
    assert chain == [ScreeningEvent, UniverseEvent, DataReadyEvent]
    assert last.cycle_id == f"XNYS:{LAST.isoformat()}:1d"

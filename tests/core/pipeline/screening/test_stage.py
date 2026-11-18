"""The screening stage: rank the universe, best first, the same way every time."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from tests.support.market import QQQ, SPY
from tests.support.recording import Recorder, TickingClock
from tyche.core.domain import (
    AssetClass,
    Currency,
    Exclusion,
    ExclusionReason,
    Instrument,
    ScoredInstrument,
    UniverseMember,
)
from tyche.core.events import EventBus, HandlerError, ScreeningEvent, UniverseEvent
from tyche.core.pipeline.screening import (
    DollarVolumeScreen,
    Screen,
    ScreeningError,
    ScreeningStage,
)

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
IWM = Instrument("IWM", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
DIA = Instrument("DIA", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)


def member(instrument: Instrument, dollar_volume: float) -> UniverseMember:
    return UniverseMember(instrument, 100.0, dollar_volume)


def screen(event: UniverseEvent, rule: Screen | None = None, **options: int) -> ScreeningEvent:
    bus = EventBus(TickingClock().now)
    ScreeningStage(bus, rule or DollarVolumeScreen(), **options)
    recorder = Recorder(bus)
    bus.publish(event, source="universe", cycle_id="c1")
    bus.drain()
    [result] = [e for e in recorder.events if isinstance(e, ScreeningEvent)]
    return result


def test_ranks_by_dollar_volume_best_first() -> None:
    universe = UniverseEvent(AS_OF, (member(SPY, 2e9), member(IWM, 5e9), member(QQQ, 3e9)))

    result = screen(universe)

    assert result.screen == "dollar_volume"
    assert result.as_of == AS_OF
    assert result.ranked == (
        ScoredInstrument(IWM, 5e9),
        ScoredInstrument(QQQ, 3e9),
        ScoredInstrument(SPY, 2e9),
    )
    assert result.cut == ()


def test_breaks_ties_by_symbol_so_the_ranking_never_depends_on_input_order() -> None:
    members = (member(SPY, 1e9), member(DIA, 1e9), member(QQQ, 1e9))

    forward = screen(UniverseEvent(AS_OF, members))
    backward = screen(UniverseEvent(AS_OF, members[::-1]))

    assert [s.instrument.symbol for s in forward.ranked] == ["DIA", "QQQ", "SPY"]
    assert forward == backward


def test_a_limit_keeps_the_best_and_lists_the_rest_as_cut() -> None:
    universe = UniverseEvent(AS_OF, (member(SPY, 2e9), member(IWM, 5e9), member(QQQ, 3e9)))

    result = screen(universe, limit=2)

    assert [s.instrument for s in result.ranked] == [IWM, QQQ]
    assert result.cut == (SPY,)


def test_excluded_instruments_are_not_ranked() -> None:
    excluded = (Exclusion(QQQ, ExclusionReason.NO_BAR, "no bar"),)

    result = screen(UniverseEvent(AS_OF, (member(SPY, 1e9),), excluded))

    assert [s.instrument for s in result.ranked] == [SPY]


def test_an_empty_universe_gives_an_empty_ranking() -> None:
    result = screen(UniverseEvent(AS_OF, ()))

    assert result.ranked == ()
    assert result.cut == ()


def test_is_published_by_screening_in_the_universes_cycle() -> None:
    bus = EventBus(TickingClock().now)
    ScreeningStage(bus, DollarVolumeScreen())
    recorder = Recorder(bus)
    bus.publish(UniverseEvent(AS_OF, (member(SPY, 1e9),)), source="universe", cycle_id="c1")
    bus.drain()

    first, second = recorder.envelopes
    assert isinstance(second.event, ScreeningEvent)
    assert (second.source, second.caused_by, second.cycle_id) == ("screening", first.seq, "c1")


@dataclass(frozen=True)
class BrokenScreen:
    name: str = "broken"

    def score(self, member: UniverseMember) -> float:
        return float("nan")


def test_a_score_that_cannot_be_ranked_halts_the_run() -> None:
    with pytest.raises(HandlerError) as raised:
        screen(UniverseEvent(AS_OF, (member(SPY, 1e9),)), BrokenScreen())

    assert isinstance(raised.value.__cause__, ScreeningError)
    assert "'broken' gave SPY@ARCX the score nan" in str(raised.value.__cause__)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_must_be_positive(limit: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ScreeningStage(EventBus(TickingClock().now), DollarVolumeScreen(), limit=limit)

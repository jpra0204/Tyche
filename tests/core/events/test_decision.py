"""Decision-cycle events check their own consistency."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    Exclusion,
    ExclusionReason,
    ScoredInstrument,
    StrategyFailure,
    Target,
    UniverseMember,
    WarmingUp,
)
from tyche.core.events import ScreeningEvent, SignalEvent, SignalsReadyEvent, UniverseEvent

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
SPY_MEMBER = UniverseMember(SPY, 470.0, 3e10)


class TestUniverseEvent:
    def test_holds_eligible_and_excluded_instruments(self) -> None:
        excluded = Exclusion(QQQ, ExclusionReason.NO_BAR, "no bar")
        event = UniverseEvent(AS_OF, (SPY_MEMBER,), (excluded,))

        assert event.eligible == (SPY_MEMBER,)
        assert str(event.excluded[0]) == "QQQ@XNAS no_bar: no bar"

    def test_an_instrument_cannot_be_both_eligible_and_excluded(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            UniverseEvent(AS_OF, (SPY_MEMBER,), (Exclusion(SPY, ExclusionReason.NO_BAR, "x"),))

    def test_as_of_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            UniverseEvent(datetime(2024, 1, 5, 16, 0), ())  # noqa: DTZ001


class TestScreeningEvent:
    def test_ranked_must_be_best_first(self) -> None:
        with pytest.raises(ValueError, match="descending"):
            ScreeningEvent(AS_OF, "s", (ScoredInstrument(SPY, 1.0), ScoredInstrument(QQQ, 2.0)))

    def test_an_instrument_cannot_be_both_ranked_and_cut(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            ScreeningEvent(AS_OF, "s", (ScoredInstrument(SPY, 1.0),), (SPY,))

    def test_needs_a_screen_name(self) -> None:
        with pytest.raises(ValueError, match="needs a name"):
            ScreeningEvent(AS_OF, "", ())

    def test_as_of_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            ScreeningEvent(datetime(2024, 1, 5, 16, 0), "s", ())  # noqa: DTZ001


class TestSignalEvent:
    def test_holds_targets_and_instruments_still_warming_up(self) -> None:
        event = SignalEvent(
            AS_OF, "trend", "1", (Target(SPY, Decimal("0.6"), "up"),), (WarmingUp(QQQ, 3, 10),)
        )

        assert [t.instrument for t in event.targets] == [SPY]
        assert event.warming_up == (WarmingUp(QQQ, 3, 10),)

    def test_weights_may_not_add_up_to_more_than_one(self) -> None:
        targets = (Target(SPY, Decimal("0.6"), "a"), Target(QQQ, Decimal("0.5"), "b"))

        with pytest.raises(ValueError, match=r"add up to 1\.1"):
            SignalEvent(AS_OF, "trend", "1", targets)

    def test_an_instrument_cannot_be_targeted_and_warming_up(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            SignalEvent(
                AS_OF, "trend", "1", (Target(SPY, Decimal(1), "a"),), (WarmingUp(SPY, 1, 2),)
            )

    def test_needs_a_valid_id_and_a_version(self) -> None:
        with pytest.raises(ValueError, match="invalid strategy id"):
            SignalEvent(AS_OF, "Trend", "1", ())
        with pytest.raises(ValueError, match="version"):
            SignalEvent(AS_OF, "trend", "", ())


class TestSignalsReadyEvent:
    def test_a_strategy_cannot_both_report_and_fail(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            SignalsReadyEvent(AS_OF, ("trend",), (StrategyFailure("trend", "boom"),))

    def test_as_of_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            SignalsReadyEvent(datetime(2024, 1, 5, 16, 0), ())  # noqa: DTZ001

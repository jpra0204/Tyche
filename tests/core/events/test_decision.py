"""Decision-cycle events check their own consistency."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    Contribution,
    Currency,
    Exclusion,
    ExclusionReason,
    Instrument,
    InstrumentTarget,
    Money,
    OrderAdjustment,
    RiskAction,
    RiskAdjustment,
    RiskRule,
    RiskScope,
    ScoredInstrument,
    Sleeve,
    SleeveStatus,
    StrategyFailure,
    Target,
    UniverseMember,
    WarmingUp,
)
from tyche.core.events import (
    KEEP,
    ApprovedPortfolioEvent,
    RiskEvent,
    ScreeningEvent,
    SignalEvent,
    SignalsReadyEvent,
    TargetPortfolioEvent,
    UniverseEvent,
)

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
            AS_OF,
            "trend",
            "1",
            (SPY,),
            (Target(SPY, Decimal("0.6"), "up"),),
            (WarmingUp(QQQ, 3, 10),),
        )

        assert [t.instrument for t in event.targets] == [SPY]
        assert event.warming_up == (WarmingUp(QQQ, 3, 10),)

    def test_weights_may_not_add_up_to_more_than_one(self) -> None:
        targets = (Target(SPY, Decimal("0.6"), "a"), Target(QQQ, Decimal("0.5"), "b"))

        with pytest.raises(ValueError, match=r"add up to 1\.1"):
            SignalEvent(AS_OF, "trend", "1", (SPY, QQQ), targets)

    def test_an_instrument_cannot_be_offered_and_warming_up(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            SignalEvent(AS_OF, "trend", "1", (SPY,), (), (WarmingUp(SPY, 1, 2),))

    def test_targets_only_instruments_it_was_offered(self) -> None:
        with pytest.raises(ValueError, match="not offered"):
            SignalEvent(AS_OF, "trend", "1", (QQQ,), (Target(SPY, Decimal(1), "a"),))

    def test_an_instrument_cannot_be_targeted_twice(self) -> None:
        twice = (Target(SPY, Decimal("0.5"), "a"), Target(SPY, Decimal("0.5"), "b"))

        with pytest.raises(ValueError, match="targeted more than once"):
            SignalEvent(AS_OF, "trend", "1", (SPY,), twice)

    def test_needs_a_valid_id_and_a_version(self) -> None:
        with pytest.raises(ValueError, match="invalid strategy id"):
            SignalEvent(AS_OF, "Trend", "1", (), ())
        with pytest.raises(ValueError, match="version"):
            SignalEvent(AS_OF, "trend", "", (), ())


class TestSignalsReadyEvent:
    def test_a_strategy_cannot_both_report_and_fail(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            SignalsReadyEvent(AS_OF, ("trend",), (StrategyFailure("trend", "boom"),))

    def test_as_of_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            SignalsReadyEvent(datetime(2024, 1, 5, 16, 0), ())  # noqa: DTZ001


def decided(strategy_id: str, budget: str, *on: Instrument) -> Sleeve:
    return Sleeve(strategy_id, Decimal(budget), SleeveStatus.DECIDED, on, "1")


def target(instrument: Instrument, *parts: tuple[str, str]) -> InstrumentTarget:
    return InstrumentTarget(instrument, tuple(Contribution(s, Decimal(w), "r") for s, w in parts))


class TestTargetPortfolioEvent:
    def test_holds_sleeves_and_targets(self) -> None:
        event = TargetPortfolioEvent(
            AS_OF,
            (decided("a", "0.6", SPY, QQQ), decided("b", "0.4", SPY)),
            (target(QQQ, ("a", "0.3")), target(SPY, ("a", "0.3"), ("b", "0.4"))),
        )

        assert event.sleeve("b").budget == Decimal("0.4")
        with pytest.raises(KeyError):
            event.sleeve("c")

    def test_sleeves_and_targets_have_a_fixed_order(self) -> None:
        with pytest.raises(ValueError, match="by id"):
            TargetPortfolioEvent(AS_OF, (decided("b", "0.4"), decided("a", "0.4")))
        with pytest.raises(ValueError, match="by symbol"):
            TargetPortfolioEvent(
                AS_OF,
                (decided("a", "0.6", SPY, QQQ),),
                (target(SPY, ("a", "0.1")), target(QQQ, ("a", "0.1"))),
            )

    def test_budgets_cannot_exceed_the_account(self) -> None:
        with pytest.raises(ValueError, match="budgets add up"):
            TargetPortfolioEvent(AS_OF, (decided("a", "0.6"), decided("b", "0.6")))

    def test_a_contribution_needs_a_decided_sleeve_that_decided_on_the_instrument(self) -> None:
        failed = Sleeve("a", Decimal("0.5"), SleeveStatus.FAILED, error="boom")

        with pytest.raises(ValueError, match="without a decided sleeve"):
            TargetPortfolioEvent(AS_OF, (failed,), (target(SPY, ("a", "0.1")),))
        with pytest.raises(ValueError, match="without a decided sleeve"):
            TargetPortfolioEvent(AS_OF, (), (target(SPY, ("a", "0.1")),))
        with pytest.raises(ValueError, match="did not decide on"):
            TargetPortfolioEvent(AS_OF, (decided("a", "0.5", QQQ),), (target(SPY, ("a", "0.1")),))

    def test_a_sleeve_cannot_use_more_than_its_budget(self) -> None:
        with pytest.raises(ValueError, match="more than its budget"):
            TargetPortfolioEvent(
                AS_OF,
                (decided("a", "0.5", SPY, QQQ),),
                (target(QQQ, ("a", "0.3")), target(SPY, ("a", "0.3"))),
            )


class TestApprovedPortfolioEvent:
    def approved(self, *targets: InstrumentTarget, **kwargs: object) -> ApprovedPortfolioEvent:
        sleeves = (
            decided("a", "0.6", SPY, QQQ),
            Sleeve("b", Decimal("0.4"), SleeveStatus.FAILED, error="boom"),
        )
        return ApprovedPortfolioEvent(AS_OF, sleeves, targets, "pass-through")

    def test_reads_each_sleeve_and_instrument_as_adr_0022_says(self) -> None:
        event = self.approved(target(SPY, ("a", "0.6")))

        contribution = event.wanted("a", SPY)
        assert contribution is not None
        assert contribution is not KEEP
        assert contribution.weight == Decimal("0.6")
        assert event.wanted("a", QQQ) is None  # decided on, not targeted: zero
        assert event.wanted("b", SPY) is KEEP  # the sleeve failed

    def test_an_instrument_not_offered_is_kept(self) -> None:
        other = Instrument("IWM", "ARCX", SPY.currency, "XNYS", SPY.asset_class)

        assert self.approved().wanted("a", other) is KEEP

    def test_follows_the_same_rules_as_a_proposed_portfolio(self) -> None:
        with pytest.raises(ValueError, match=r"ApprovedPortfolioEvent: .* more than its budget"):
            self.approved(target(QQQ, ("a", "0.3")), target(SPY, ("a", "0.4")))

    def test_needs_a_profile_name(self) -> None:
        with pytest.raises(ValueError, match="risk profile"):
            ApprovedPortfolioEvent(AS_OF, (decided("a", "1"),), (), " ")

    def test_an_unknown_sleeve_is_a_key_error(self) -> None:
        with pytest.raises(KeyError):
            self.approved().wanted("z", SPY)


class TestRiskEvent:
    def adjustment(self) -> RiskAdjustment:
        return RiskAdjustment(
            RiskRule.MAX_POSITION_SIZE,
            RiskScope.ACCOUNT,
            RiskAction.SHRINK,
            "a",
            SPY,
            Decimal("0.5"),
            Decimal("0.2"),
            Decimal("0.2"),
            "too big",
        )

    def test_carries_the_profile_and_the_adjustment(self) -> None:
        adjustment = self.adjustment()
        event = RiskEvent(AS_OF, "default", adjustment)
        assert (event.profile, event.adjustment) == ("default", adjustment)

    def test_needs_a_profile(self) -> None:
        with pytest.raises(ValueError, match="needs the name of the risk profile"):
            RiskEvent(AS_OF, " ", self.adjustment())

    def test_needs_a_utc_time(self) -> None:
        with pytest.raises(ValueError, match="as_of"):
            RiskEvent(datetime(2024, 1, 5, 21, 0), "default", self.adjustment())  # noqa: DTZ001

    def test_carries_an_order_adjustment_from_execution(self) -> None:
        cut = OrderAdjustment(
            RiskRule.MAX_ORDER_VALUE,
            RiskAction.SHRINK,
            SPY,
            Decimal(50),
            Decimal(6),
            Money.of("690", Currency.USD),
            "over the cap",
        )
        assert RiskEvent(AS_OF, "default", cut).adjustment.scope is RiskScope.ORDER

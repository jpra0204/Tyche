"""The risk gate's position rules (ADR-0033)."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY, bar
from tests.support.recording import Recorder, TickingClock
from tests.support.risk import DEFAULT, UNBOUND, guardrails, profile
from tyche.core.domain import (
    Account,
    AssetClass,
    Contribution,
    Currency,
    Instrument,
    InstrumentTarget,
    Money,
    RiskAction,
    RiskAdjustment,
    RiskRule,
    RiskScope,
    Sleeve,
    SleeveStatus,
)
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    EventBus,
    HandlerError,
    RiskEvent,
    TargetPortfolioEvent,
)
from tyche.core.risk import (
    RiskGate,
    RiskGateError,
    RiskLimits,
    StrategyRiskLimits,
    review,
)

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
IWM = Instrument("IWM", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
EFA = Instrument("EFA", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
EEM = Instrument("EEM", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
ALL = (EEM, EFA, IWM, QQQ, SPY)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def decided(strategy_id: str, budget: str = "1", on: tuple[Instrument, ...] = ALL) -> Sleeve:
    return Sleeve(strategy_id, Decimal(budget), SleeveStatus.DECIDED, on, "1")


def proposal(
    wants: Mapping[Instrument, Mapping[str, str | tuple[str, str]]],
    sleeves: tuple[Sleeve, ...] | None = None,
) -> TargetPortfolioEvent:
    """A proposal from ``{instrument: {strategy: weight or (weight, stop)}}``."""
    targets = []
    for instrument in sorted(wants, key=lambda i: (i.symbol, i.exchange)):
        contributions = []
        for strategy_id, wanted in sorted(wants[instrument].items()):
            weight, stop = wanted if isinstance(wanted, tuple) else (wanted, None)
            contributions.append(
                Contribution(strategy_id, Decimal(weight), "wanted", usd(stop) if stop else None)
            )
        targets.append(InstrumentTarget(instrument, tuple(contributions)))
    if sleeves is None:
        ids = sorted({s for by in wants.values() for s in by})
        budget = str(Decimal(1) / len(ids))
        sleeves = tuple(decided(s, budget) for s in ids)
    return TargetPortfolioEvent(AS_OF, sleeves, tuple(targets))


def approved(result_targets: tuple[InstrumentTarget, ...]) -> dict[tuple[str, str], Decimal]:
    return {
        (c.strategy_id, t.instrument.symbol): c.weight
        for t in result_targets
        for c in t.contributions
    }


CLOSES = {i: usd("100") for i in ALL}


def limits(
    *,
    risk_per_trade: str = "1",
    open_positions: int = 1000,
    position_size: str = "1",
    strategies: Mapping[str, StrategyRiskLimits] | None = None,
) -> RiskLimits:
    return RiskLimits(
        guardrails(),
        profile(
            risk_per_trade=risk_per_trade,
            open_positions=open_positions,
            position_size=position_size,
        ),
        strategies or {},
    )


class TestWithinTheLimits:
    def test_approves_the_proposal_as_it_is(self) -> None:
        proposed = proposal({SPY: {"a": "0.5"}, QQQ: {"a": "0.5"}})
        result = review(proposed, {}, CLOSES, UNBOUND)
        assert result.targets == proposed.targets
        assert result.adjustments == ()

    def test_keeps_a_target_of_zero_which_sells(self) -> None:
        proposed = proposal({SPY: {"a": "0"}})
        result = review(proposed, {("a", SPY): Decimal("0.5")}, CLOSES, DEFAULT)
        assert result.targets == proposed.targets


class TestRiskPerTrade:
    def test_sizes_an_entry_so_the_stop_loses_at_most_the_limit(self) -> None:
        # Close 100, stop 95: 5% of the position is at risk, so 1% of equity allows 20%.
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        result = review(proposed, {}, CLOSES, limits(risk_per_trade="0.01"))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.2")}
        [adjustment] = result.adjustments
        assert (adjustment.rule, adjustment.scope, adjustment.action) == (
            RiskRule.RISK_PER_TRADE,
            RiskScope.STRATEGY,
            RiskAction.SHRINK,
        )
        assert (adjustment.before, adjustment.after, adjustment.limit) == (
            Decimal("0.5"),
            Decimal("0.2"),
            Decimal("0.01"),
        )

    def test_rounds_down_so_the_limit_is_never_exceeded(self) -> None:
        # 0.01 * 100 / 3 = 0.3333...: approved as 0.333333333333, never above.
        proposed = proposal({SPY: {"a": ("0.5", "97")}})
        result = review(proposed, {}, CLOSES, limits(risk_per_trade="0.01"))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.333333333333")}

    def test_leaves_a_target_without_a_stop_alone(self) -> None:
        proposed = proposal({SPY: {"a": "0.5"}})
        assert review(proposed, {}, CLOSES, limits(risk_per_trade="0.01")).adjustments == ()

    def test_blocks_an_entry_whose_stop_is_not_below_the_close(self) -> None:
        proposed = proposal({SPY: {"a": ("0.5", "100")}})
        result = review(proposed, {}, CLOSES, limits(risk_per_trade="0.01"))
        assert result.targets == ()
        assert result.adjustments[0].action is RiskAction.BLOCK

    def test_limits_an_addition_by_the_whole_position(self) -> None:
        held = {("a", SPY): Decimal("0.1")}
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        result = review(proposed, held, CLOSES, limits(risk_per_trade="0.01"))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.2")}

    def test_never_trims_a_holding_already_above_the_limit(self) -> None:
        # A winner: the stop is far below now, so the whole position risks more than 1%.
        # The addition is refused; what is held is kept, not cut.
        held = {("a", SPY): Decimal("0.3")}
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        result = review(proposed, held, CLOSES, limits(risk_per_trade="0.01"))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.3")}
        assert "already holds" in result.adjustments[0].reason

    def test_does_not_apply_to_a_holding_that_is_not_added_to(self) -> None:
        held = {("a", SPY): Decimal("0.5")}
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        assert review(proposed, held, CLOSES, limits(risk_per_trade="0.01")).adjustments == ()

    def test_uses_a_strategys_own_stricter_limit(self) -> None:
        own = {"a": StrategyRiskLimits(risk_per_trade=Decimal("0.005"))}
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        result = review(proposed, {}, CLOSES, limits(risk_per_trade="0.01", strategies=own))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.1")}

    def test_needs_the_close_of_an_instrument_entered_with_a_stop(self) -> None:
        proposed = proposal({SPY: {"a": ("0.5", "95")}})
        with pytest.raises(RiskGateError, match="no closing price"):
            review(proposed, {}, {}, limits(risk_per_trade="0.01"))


class TestPositionSize:
    def test_caps_an_instrument_held_by_one_sleeve(self) -> None:
        result = review(proposal({SPY: {"a": "1"}}), {}, CLOSES, DEFAULT)
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.2")}
        [adjustment] = result.adjustments
        assert (adjustment.rule, adjustment.scope) == (
            RiskRule.MAX_POSITION_SIZE,
            RiskScope.ACCOUNT,
        )

    def test_shrinks_every_sleeve_by_the_same_proportion(self) -> None:
        proposed = proposal({SPY: {"a": "0.3", "b": "0.1"}})
        result = review(proposed, {}, CLOSES, DEFAULT)
        assert approved(result.targets) == {
            ("a", "SPY"): Decimal("0.15"),
            ("b", "SPY"): Decimal("0.05"),
        }

    def test_applies_to_what_is_held_too(self) -> None:
        held = {("a", SPY): Decimal("0.3")}
        result = review(proposal({SPY: {"a": "0.3"}}), held, CLOSES, DEFAULT)
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.2")}

    def test_counts_what_a_sleeve_keeps_without_deciding(self) -> None:
        # b holds 15% of SPY and was not offered it this cycle: it keeps it, so a may
        # add only 5% before the instrument reaches 20%.
        sleeves = (decided("a", "0.5"), decided("b", "0.5", on=(QQQ,)))
        held = {("b", SPY): Decimal("0.15")}
        result = review(proposal({SPY: {"a": "0.2"}}, sleeves), held, CLOSES, DEFAULT)
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.05")}

    def test_uses_a_strategys_own_cap_on_its_contribution(self) -> None:
        own = {"a": StrategyRiskLimits(max_position_size=Decimal("0.1"))}
        result = review(proposal({SPY: {"a": "0.5"}}), {}, CLOSES, limits(strategies=own))
        assert approved(result.targets) == {("a", "SPY"): Decimal("0.1")}
        assert result.adjustments[0].scope is RiskScope.STRATEGY


class TestOpenPositions:
    def test_new_entries_fill_the_free_places_largest_first(self) -> None:
        held = {("a", SPY): Decimal("0.2")}
        wants = {SPY: {"a": "0.2"}, QQQ: {"a": "0.1"}, IWM: {"a": "0.3"}, EFA: {"a": "0.2"}}
        result = review(proposal(wants), held, CLOSES, limits(open_positions=3))
        assert set(approved(result.targets)) == {("a", "SPY"), ("a", "IWM"), ("a", "EFA")}
        [blocked] = result.adjustments
        assert blocked.instrument == QQQ
        assert (blocked.rule, blocked.scope, blocked.action) == (
            RiskRule.MAX_OPEN_POSITIONS,
            RiskScope.ACCOUNT,
            RiskAction.BLOCK,
        )

    def test_ties_go_by_symbol(self) -> None:
        wants = {QQQ: {"a": "0.2"}, IWM: {"a": "0.2"}, EFA: {"a": "0.2"}}
        result = review(proposal(wants), {}, CLOSES, limits(open_positions=2))
        assert set(approved(result.targets)) == {("a", "EFA"), ("a", "IWM")}

    def test_held_positions_keep_their_place_even_when_smaller(self) -> None:
        held = {("a", SPY): Decimal("0.05")}
        wants = {SPY: {"a": "0.05"}, QQQ: {"a": "0.5"}}
        result = review(proposal(wants), held, CLOSES, limits(open_positions=1))
        assert set(approved(result.targets)) == {("a", "SPY")}

    def test_a_holding_sold_to_zero_frees_its_place(self) -> None:
        held = {("a", SPY): Decimal("0.5")}
        wants = {SPY: {"a": "0"}, QQQ: {"a": "0.5"}}
        result = review(proposal(wants), held, CLOSES, limits(open_positions=1))
        assert approved(result.targets) == {("a", "SPY"): Decimal(0), ("a", "QQQ"): Decimal("0.5")}

    def test_a_holding_not_decided_on_keeps_its_place(self) -> None:
        held = {("a", SPY): Decimal("0.5")}
        sleeves = (decided("a", on=(QQQ,)),)
        result = review(
            proposal({QQQ: {"a": "0.5"}}, sleeves), held, CLOSES, limits(open_positions=1)
        )
        assert result.targets == ()

    def test_adding_to_an_instrument_another_sleeve_holds_takes_no_new_place(self) -> None:
        held = {("b", SPY): Decimal("0.2")}
        wants = {SPY: {"a": "0.1", "b": "0.2"}, QQQ: {"a": "0.1"}}
        result = review(proposal(wants), held, CLOSES, limits(open_positions=2))
        assert result.adjustments == ()

    def test_a_strategys_own_count_is_of_its_own_sleeve(self) -> None:
        own = {"a": StrategyRiskLimits(max_open_positions=1)}
        held = {("b", SPY): Decimal("0.2")}
        wants = {SPY: {"a": "0.1", "b": "0.2"}, QQQ: {"a": "0.2"}}
        result = review(proposal(wants), held, CLOSES, limits(strategies=own))
        assert approved(result.targets) == {
            ("a", "QQQ"): Decimal("0.2"),
            ("b", "SPY"): Decimal("0.2"),
        }
        assert result.adjustments[0].scope is RiskScope.STRATEGY

    def test_an_entry_blocked_by_its_stop_takes_no_place(self) -> None:
        wants: dict[Instrument, dict[str, str | tuple[str, str]]] = {
            SPY: {"a": ("0.3", "100")},
            QQQ: {"a": "0.2"},
        }
        result = review(
            proposal(wants), {}, CLOSES, limits(risk_per_trade="0.01", open_positions=1)
        )
        assert approved(result.targets) == {("a", "QQQ"): Decimal("0.2")}


class TestLimits:
    def test_refuse_a_profile_above_the_guardrails(self) -> None:
        with pytest.raises(ValueError, match="exceeds the guardrails"):
            RiskLimits(guardrails(position_size="0.1"), profile(position_size="0.2"))

    def test_refuse_a_strategy_looser_than_the_profile(self) -> None:
        own = {"a": StrategyRiskLimits(max_position_size=Decimal("0.3"))}
        with pytest.raises(ValueError, match="looser than profile"):
            RiskLimits(guardrails(), profile(position_size="0.2"), own)


class TestApprovedPortfolioEvent:
    def adjustment(self, before: str, after: str) -> RiskAdjustment:
        action = RiskAction.BLOCK if Decimal(after) == 0 else RiskAction.SHRINK
        return RiskAdjustment(
            RiskRule.MAX_POSITION_SIZE,
            RiskScope.ACCOUNT,
            action,
            "a",
            SPY,
            Decimal(before),
            Decimal(after),
            Decimal("0.2"),
            "too big",
        )

    def test_refuses_an_adjustment_that_does_not_match_the_target(self) -> None:
        proposed = proposal({SPY: {"a": "0.3"}})
        with pytest.raises(ValueError, match=r"adjusted to 0\.2"):
            ApprovedPortfolioEvent(
                AS_OF,
                proposed.sleeves,
                proposed.targets,
                "default",
                (self.adjustment("0.5", "0.2"),),
            )

    def test_refuses_adjustments_that_do_not_follow_on(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        with pytest.raises(ValueError, match="do not follow on"):
            ApprovedPortfolioEvent(
                AS_OF,
                proposed.sleeves,
                proposed.targets,
                "default",
                (self.adjustment("0.5", "0.2"), self.adjustment("0.3", "0.1")),
            )

    def test_refuses_a_contribution_left_after_a_block(self) -> None:
        proposed = proposal({SPY: {"a": "0"}})
        with pytest.raises(ValueError, match="adjusted to 0"):
            ApprovedPortfolioEvent(
                AS_OF, proposed.sleeves, proposed.targets, "default", (self.adjustment("0.5", "0"),)
            )


class FakeHoldings:
    def __init__(self, shares: Mapping[tuple[str, Instrument], str]) -> None:
        self._shares = {k: Decimal(v) for k, v in shares.items()}

    @property
    def instruments(self) -> tuple[Instrument, ...]:
        return tuple(sorted({i for _, i in self._shares}, key=lambda i: i.symbol))

    def holders(self, instrument: Instrument) -> tuple[str, ...]:
        return tuple(sorted(s for s, i in self._shares if i == instrument))

    def held(self, strategy_id: str, instrument: Instrument) -> Decimal:
        return self._shares.get((strategy_id, instrument), Decimal(0))


class TestRiskGate:
    def run(
        self,
        proposed: TargetPortfolioEvent,
        *,
        account_as_of: datetime = AS_OF,
        cash: str = "10000",
        closes: tuple[Instrument, ...] = (SPY,),
    ) -> Recorder:
        bus = EventBus(TickingClock().now)
        RiskGate(bus, DEFAULT, FakeHoldings({("a", SPY): "20"}))
        recorder = Recorder(bus)
        for instrument in closes:
            bus.publish(
                BarEvent(bar(date(2024, 1, 5), 100.0, instrument=instrument)), source="feed"
            )
        account = Account.empty()
        if Decimal(cash) > 0:
            account = account.deposit(usd(cash))
        bus.publish(AccountEvent(account_as_of, account), source="account")
        bus.publish(proposed, source="portfolio")
        bus.drain()
        return recorder

    def test_publishes_each_adjustment_then_the_approved_portfolio(self) -> None:
        # a holds 20 SPY at 100 of 10,000: 20%. QQQ has no stop, so it needs no close.
        proposed = proposal({SPY: {"a": "0.5"}, QQQ: {"a": "0.3"}})
        recorder = self.run(proposed)

        risk = [e for e in recorder if isinstance(e.event, RiskEvent)]
        cuts = [e.event for e in recorder if isinstance(e.event, RiskEvent)]
        [approval] = [e for e in recorder if isinstance(e.event, ApprovedPortfolioEvent)]
        [approved_event] = [
            e.event for e in recorder if isinstance(e.event, ApprovedPortfolioEvent)
        ]
        assert [c.adjustment.instrument for c in cuts] == [QQQ, SPY]
        assert all(c.profile == "default" for c in cuts)
        assert all(e.source == "risk" for e in [*risk, approval])
        assert risk[-1].seq < approval.seq
        assert approved_event.profile == "default"
        assert approved_event.adjustments == tuple(c.adjustment for c in cuts)
        assert approved(approved_event.targets) == {
            ("a", "QQQ"): Decimal("0.2"),
            ("a", "SPY"): Decimal("0.2"),
        }
        target_seq = next(e.seq for e in recorder if isinstance(e.event, TargetPortfolioEvent))
        assert approval.caused_by == target_seq

    def test_halts_without_an_account_snapshot_of_the_same_close(self) -> None:
        with pytest.raises(HandlerError) as raised:
            self.run(
                proposal({SPY: {"a": "0.1"}}), account_as_of=datetime(2024, 1, 4, 21, tzinfo=UTC)
            )
        assert isinstance(raised.value.__cause__, RiskGateError)

    def test_halts_without_the_close_of_a_held_instrument(self) -> None:
        with pytest.raises(HandlerError) as raised:
            self.run(proposal({QQQ: {"a": "0.1"}}), closes=())
        assert isinstance(raised.value.__cause__, RiskGateError)
        assert "which is held" in str(raised.value.__cause__)

    def test_halts_on_an_account_with_nothing_in_it(self) -> None:
        with pytest.raises(HandlerError) as raised:
            self.run(proposal({SPY: {"a": "0.1"}}), cash="0")
        assert "equity in USD is 0" in str(raised.value.__cause__)

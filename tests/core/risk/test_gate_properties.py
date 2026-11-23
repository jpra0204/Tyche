"""Property-based tests: no proposal yields an approved portfolio that breaks a limit.

Hypothesis draws proposals (sleeves, weights, stops), what each sleeve holds, closing
prices and the limits of every layer, and checks every limit on what the gate
approves. Because each profile is within its guardrails (``RiskLimits`` refuses
anything else), keeping to the profile also keeps to the guardrails.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from hypothesis import given
from hypothesis import strategies as st

from tests.support.risk import guardrails, profile
from tyche.core.domain import (
    AssetClass,
    Contribution,
    Currency,
    Instrument,
    InstrumentTarget,
    Money,
    Sleeve,
    SleeveStatus,
)
from tyche.core.events import ApprovedPortfolioEvent, TargetPortfolioEvent
from tyche.core.risk import WEIGHT_PLACES, RiskLimits, StrategyRiskLimits, review

INSTRUMENTS = tuple(
    Instrument(symbol, "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
)
SLEEVES = ("a", "b", "c")
AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)

type Key = tuple[str, Instrument]


@dataclass(frozen=True)
class Case:
    proposed: TargetPortfolioEvent
    held: dict[Key, Decimal]
    closes: dict[Instrument, Money]
    limits: RiskLimits


def fraction(low: str, high: str, places: int = 4) -> st.SearchStrategy[Decimal]:
    return st.decimals(Decimal(low), Decimal(high), places=places)


@st.composite
def cases(draw: st.DrawFn) -> Case:
    ids = draw(st.lists(st.sampled_from(SLEEVES), min_size=1, max_size=3, unique=True))
    ids.sort()
    budget = (Decimal(1) / len(ids)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    instruments = draw(st.lists(st.sampled_from(INSTRUMENTS), min_size=1, max_size=6, unique=True))
    closes = {i: Money(draw(fraction("1", "500", 2)), Currency.USD) for i in INSTRUMENTS}

    sleeves: list[Sleeve] = []
    contributions: dict[Instrument, list[Contribution]] = {}
    for strategy_id in ids:
        if draw(st.booleans()) and draw(st.booleans()):  # a quarter of sleeves fail
            sleeves.append(Sleeve(strategy_id, budget, SleeveStatus.FAILED, error="failed"))
            continue
        decided_on = draw(st.lists(st.sampled_from(instruments), unique=True))
        sleeves.append(Sleeve(strategy_id, budget, SleeveStatus.DECIDED, tuple(decided_on), "1"))
        each = (budget / max(len(decided_on), 1)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        for instrument in decided_on:
            if not draw(st.booleans()):
                continue
            weight = draw(fraction("0", str(each)))
            stop = None
            if draw(st.booleans()):
                close = closes[instrument].amount
                stop = Money(draw(fraction("0.01", str(close * 2), 2)), Currency.USD)
            contributions.setdefault(instrument, []).append(
                Contribution(strategy_id, weight, "wanted", stop)
            )
    targets = tuple(
        InstrumentTarget(i, tuple(contributions[i]))
        for i in sorted(contributions, key=lambda i: (i.symbol, i.exchange))
    )
    proposed = TargetPortfolioEvent(AS_OF, tuple(sleeves), targets)

    held = {
        (s, i): draw(fraction("0.0001", "0.2", 6))
        for s in ids
        for i in instruments
        if draw(st.integers(0, 3)) == 0
    }

    risk_per_trade = draw(fraction("0.001", "1"))
    open_positions = draw(st.integers(1, 6))
    position_size = draw(fraction("0.01", "1"))
    own: dict[str, StrategyRiskLimits] = {}
    for strategy_id in ids:
        if draw(st.booleans()):
            own[strategy_id] = StrategyRiskLimits(
                risk_per_trade=draw(st.none() | fraction("0.001", str(risk_per_trade))),
                max_open_positions=draw(st.none() | st.integers(1, open_positions)),
                max_position_size=draw(st.none() | fraction("0.01", str(position_size))),
            )
    limits = RiskLimits(
        guardrails(),
        profile(
            risk_per_trade=str(risk_per_trade),
            open_positions=open_positions,
            position_size=str(position_size),
        ),
        own,
    )
    return Case(proposed, held, closes, limits)


def weights(targets: tuple[InstrumentTarget, ...]) -> dict[Key, Decimal]:
    return {(c.strategy_id, t.instrument): c.weight for t in targets for c in t.contributions}


def kept(case: Case, strategy_id: str, instrument: Instrument) -> bool:
    for sleeve in case.proposed.sleeves:
        if sleeve.strategy_id == strategy_id:
            return sleeve.status is SleeveStatus.FAILED or instrument not in sleeve.decided_on
    return True


def staying(case: Case, approved: dict[Key, Decimal], keys: list[Key]) -> set[Key]:
    return {k for k in keys if kept(case, *k) or approved.get(k, Decimal(0)) > 0}


@given(cases())
def test_the_approved_portfolio_is_a_valid_event(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    ApprovedPortfolioEvent(AS_OF, case.proposed.sleeves, result.targets, "test", result.adjustments)


@given(cases())
def test_the_gate_only_lowers_or_removes_contributions(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    proposed = {
        (c.strategy_id, t.instrument): c for t in case.proposed.targets for c in t.contributions
    }
    for target in result.targets:
        for contribution in target.contributions:
            before = proposed[(contribution.strategy_id, target.instrument)]
            assert contribution.weight <= before.weight
            assert contribution.stop_price == before.stop_price
            assert contribution.reason == before.reason


@given(cases())
def test_no_instrument_is_larger_than_the_profile_allows(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    cap = case.limits.profile.max_position_size
    for target in result.targets:
        approved = target.weight
        keeping = sum(
            (w for (s, i), w in case.held.items() if i == target.instrument and kept(case, s, i)),
            start=Decimal(0),
        )
        assert approved == 0 or approved + keeping <= cap


@given(cases())
def test_no_sleeve_is_larger_than_its_own_cap(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    for (strategy_id, _), weight in weights(result.targets).items():
        cap = case.limits.of_strategy(strategy_id).max_position_size
        assert cap is None or weight <= cap


@given(cases())
def test_no_entry_or_addition_risks_more_than_risk_per_trade(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    for target in result.targets:
        close = case.closes[target.instrument].amount
        for contribution in target.contributions:
            holding = case.held.get((contribution.strategy_id, target.instrument), Decimal(0))
            stop = contribution.stop_price
            if stop is None or contribution.weight <= holding:
                continue
            # An addition may keep, rounded up, what is already held; beyond that, the
            # loss from the close to the stop is at most risk per trade of equity.
            if contribution.weight == holding.quantize(WEIGHT_PLACES, rounding=ROUND_CEILING):
                continue
            rate = case.limits.of_strategy(contribution.strategy_id).risk_per_trade
            assert stop.amount < close
            assert contribution.weight * (close - stop.amount) <= rate * close


@given(cases())
def test_new_positions_only_fill_free_places(case: Case) -> None:
    result = review(case.proposed, case.held, case.closes, case.limits)
    approved = {k: w for k, w in weights(result.targets).items() if w > 0}

    held_instruments = {i for _, i in case.held}
    stay = {i for _, i in staying(case, approved, list(case.held))}
    new = {i for _, i in approved if i not in held_instruments}
    assert len(new) <= max(case.limits.profile.max_open_positions - len(stay), 0)

    for strategy_id in SLEEVES:
        limit = case.limits.of_strategy(strategy_id).max_open_positions
        if limit is None:
            continue
        mine = [k for k in case.held if k[0] == strategy_id]
        entries = {k for k in approved if k[0] == strategy_id and k not in case.held}
        assert len(entries) <= max(limit - len(staying(case, approved, mine)), 0)

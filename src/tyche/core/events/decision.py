"""Decision-cycle events: what each pipeline stage concluded.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from tyche.core.domain import (
    Contribution,
    Exclusion,
    Instrument,
    InstrumentTarget,
    ScoredInstrument,
    Sleeve,
    SleeveStatus,
    StrategyFailure,
    Target,
    UniverseMember,
    WarmingUp,
    require_strategy_id,
)
from tyche.core.domain.validation import require_utc
from tyche.core.events.event import Event


@dataclass(frozen=True, slots=True)
class UniverseEvent(Event):
    """Which instruments are eligible at one decision time. Published once per cycle.

    Every instrument the feed expected at ``as_of`` appears exactly once, either in
    ``eligible`` or in ``excluded``, so the journal can always say why an instrument
    was not traded.

    Attributes:
        as_of: The decision time, copied from the ``DataReadyEvent``.
        eligible: Instruments that passed every rule, with their measurements, in the
            feed's order.
        excluded: Instruments that failed a rule, each with the first rule it failed,
            in the feed's order.
    """

    as_of: datetime
    eligible: tuple[UniverseMember, ...]
    excluded: tuple[Exclusion, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "UniverseEvent as_of")
        instruments = [m.instrument for m in self.eligible] + [e.instrument for e in self.excluded]
        if len(set(instruments)) != len(instruments):
            raise ValueError("UniverseEvent: an instrument appears more than once")


@dataclass(frozen=True, slots=True)
class ScreeningEvent(Event):
    """The eligible instruments, ranked by one screen. Published once per cycle.

    Attributes:
        as_of: The decision time, copied from the ``UniverseEvent``.
        screen: Name of the screen that produced the ranking.
        ranked: The instruments kept, best first.
        cut: Eligible instruments ranked below the screen's limit, best first. Empty
            when the screen has no limit.
    """

    as_of: datetime
    screen: str
    ranked: tuple[ScoredInstrument, ...]
    cut: tuple[Instrument, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "ScreeningEvent as_of")
        if not self.screen:
            raise ValueError("ScreeningEvent: screen needs a name")
        instruments = [s.instrument for s in self.ranked] + list(self.cut)
        if len(set(instruments)) != len(instruments):
            raise ValueError("ScreeningEvent: an instrument appears more than once")
        scores = [s.score for s in self.ranked]
        if scores != sorted(scores, reverse=True):
            raise ValueError("ScreeningEvent: ranked must be in descending order of score")


@dataclass(frozen=True, slots=True)
class SignalEvent(Event):
    """What one strategy wants to hold at one decision time (ADR-0021).

    Published by the signals stage for each strategy that decided successfully, before
    the cycle's ``SignalsReadyEvent``.

    How portfolio construction reads ``targets`` (PR 13):

    * an instrument in ``targets`` gets that weight of the strategy's budget;
    * an instrument the strategy was offered and did not target gets zero;
    * an instrument the strategy holds but was not offered this cycle (not ranked, or
      in ``warming_up``) keeps its position: a data gap is not a decision to sell.

    Attributes:
        as_of: The decision time, copied from the ``ScreeningEvent``.
        strategy_id: The strategy instance.
        strategy_version: The version of its code, recorded so a result can be traced
            to the code that produced it.
        offered: The instruments the strategy was offered, and so decided on, best
            ranked first. Every target is one of them.
        targets: Weights within the strategy's budget, adding up to at most 1, in the
            order the strategy returned them.
        warming_up: Ranked instruments the strategy was not offered because it does
            not have a full window of history for them yet.
    """

    as_of: datetime
    strategy_id: str
    strategy_version: str
    offered: tuple[Instrument, ...]
    targets: tuple[Target, ...]
    warming_up: tuple[WarmingUp, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "SignalEvent as_of")
        require_strategy_id(self.strategy_id)
        if not self.strategy_version.strip():
            raise ValueError(f"SignalEvent of {self.strategy_id}: needs a strategy version")
        label = f"SignalEvent of {self.strategy_id}"
        targeted = [t.instrument for t in self.targets]
        if len(set(targeted)) != len(targeted):
            raise ValueError(f"{label}: an instrument is targeted more than once")
        if not set(targeted) <= set(self.offered):
            raise ValueError(f"{label}: a target is for an instrument it was not offered")
        listed = list(self.offered) + [w.instrument for w in self.warming_up]
        if len(set(listed)) != len(listed):
            raise ValueError(f"{label}: an instrument appears more than once")
        total = sum((t.weight for t in self.targets), start=Decimal(0))
        if total > 1:
            raise ValueError(f"{label}: weights add up to {total}, more than 1")


@dataclass(frozen=True, slots=True)
class SignalsReadyEvent(Event):
    """Every strategy has been asked at one decision time. Portfolio construction acts on it.

    Attributes:
        as_of: The decision time.
        reported: Strategies that published a ``SignalEvent`` this cycle, in the order
            they were asked.
        failed: Strategies that could not decide, each with the reason. They published
            nothing this cycle.
    """

    as_of: datetime
    reported: tuple[str, ...]
    failed: tuple[StrategyFailure, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "SignalsReadyEvent as_of")
        ids = list(self.reported) + [f.strategy_id for f in self.failed]
        if len(set(ids)) != len(ids):
            raise ValueError("SignalsReadyEvent: a strategy appears more than once")


class Keep(Enum):
    """The marker ``ApprovedPortfolioEvent.wanted`` returns for "keep what it holds"."""

    KEEP = "keep"


KEEP = Keep.KEEP


def _require_portfolio(
    label: str,
    as_of: datetime,
    sleeves: tuple[Sleeve, ...],
    targets: tuple[InstrumentTarget, ...],
) -> None:
    """The rules a proposed and an approved portfolio share (ADR-0022)."""
    require_utc(as_of, f"{label} as_of")
    ids = [s.strategy_id for s in sleeves]
    if ids != sorted(set(ids)):
        raise ValueError(f"{label}: sleeves must be one per strategy, by id")
    total_budget = sum((s.budget for s in sleeves), start=Decimal(0))
    if total_budget > 1:
        raise ValueError(f"{label}: budgets add up to {total_budget}")
    keys = [(t.instrument.symbol, t.instrument.exchange) for t in targets]
    if keys != sorted(set(keys)):
        raise ValueError(f"{label}: targets must be one per instrument, by symbol and exchange")
    by_id = {s.strategy_id: s for s in sleeves}
    used: dict[str, Decimal] = {}
    for target in targets:
        for contribution in target.contributions:
            sleeve = by_id.get(contribution.strategy_id)
            if sleeve is None or sleeve.status is not SleeveStatus.DECIDED:
                raise ValueError(
                    f"{label}: {contribution.strategy_id} contributes to "
                    f"{target.instrument} without a decided sleeve"
                )
            if target.instrument not in sleeve.decided_on:
                raise ValueError(
                    f"{label}: {sleeve.strategy_id} contributes to "
                    f"{target.instrument}, which it did not decide on"
                )
            used[sleeve.strategy_id] = used.get(sleeve.strategy_id, Decimal(0)) + (
                contribution.weight
            )
    for strategy_id, weight in used.items():
        if weight > by_id[strategy_id].budget:
            raise ValueError(
                f"{label}: {strategy_id} uses {weight}, more than its "
                f"budget {by_id[strategy_id].budget}"
            )


def _sleeve(sleeves: tuple[Sleeve, ...], strategy_id: str) -> Sleeve:
    for sleeve in sleeves:
        if sleeve.strategy_id == strategy_id:
            return sleeve
    raise KeyError(strategy_id)


@dataclass(frozen=True, slots=True)
class TargetPortfolioEvent(Event):
    """The proposed portfolio at one decision time, as weights of account equity (ADR-0022).

    Proposed, not approved: only the risk gate consumes it, and only the risk gate can
    publish the ``ApprovedPortfolioEvent`` that execution acts on.

    For each sleeve and instrument, execution reads it this way: a contribution from
    the sleeve gives its weight; an instrument in the sleeve's ``decided_on`` without
    one gives zero; anything else the sleeve holds is kept.

    Attributes:
        as_of: The decision time.
        sleeves: One per strategy with a budget, ordered by strategy id.
        targets: One per instrument some sleeve targeted, ordered by symbol and exchange.
    """

    as_of: datetime
    sleeves: tuple[Sleeve, ...]
    targets: tuple[InstrumentTarget, ...] = ()

    def __post_init__(self) -> None:
        _require_portfolio("TargetPortfolioEvent", self.as_of, self.sleeves, self.targets)

    def sleeve(self, strategy_id: str) -> Sleeve:
        return _sleeve(self.sleeves, strategy_id)


@dataclass(frozen=True, slots=True)
class ApprovedPortfolioEvent(Event):
    """The portfolio the risk gate approved at one decision time (ADR-0006, ADR-0022).

    The only event execution acts on, and only the risk gate publishes it. It has the
    shape of the ``TargetPortfolioEvent`` it approves, and is read the same way: per
    sleeve and instrument, a contribution gives its weight, ``decided_on`` without one
    gives zero, and anything else the sleeve holds is kept.

    In Phase 1 the gate has no rules, so the approved portfolio is the proposed one.
    The ``RiskEvent``s that explain each change are added with the rules in Phase 2.

    Attributes:
        as_of: The decision time.
        sleeves: One per strategy with a budget, ordered by strategy id.
        targets: One per instrument with an approved contribution, ordered by symbol
            and exchange.
        profile: The risk profile the gate applied. ``"pass-through"`` in Phase 1.
    """

    as_of: datetime
    sleeves: tuple[Sleeve, ...]
    targets: tuple[InstrumentTarget, ...]
    profile: str

    def __post_init__(self) -> None:
        _require_portfolio("ApprovedPortfolioEvent", self.as_of, self.sleeves, self.targets)
        if not self.profile.strip():
            raise ValueError("ApprovedPortfolioEvent: needs the name of the risk profile")

    def sleeve(self, strategy_id: str) -> Sleeve:
        return _sleeve(self.sleeves, strategy_id)

    def wanted(self, strategy_id: str, instrument: Instrument) -> Contribution | Keep | None:
        """How execution reads one sleeve and one instrument (ADR-0022, decision 4).

        Returns the sleeve's contribution if it has one; ``None`` if it decided on the
        instrument and did not target it (a target of zero); ``KEEP`` otherwise (not
        offered this cycle, or the sleeve failed): keep what it holds.
        """
        sleeve = self.sleeve(strategy_id)
        if sleeve.status is not SleeveStatus.DECIDED or instrument not in sleeve.decided_on:
            return KEEP
        for target in self.targets:
            if target.instrument == instrument:
                return target.contribution_of(strategy_id)
        return None

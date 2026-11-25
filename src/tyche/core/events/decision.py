"""Decision-cycle events: what each pipeline stage concluded.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from tyche.core.domain import (
    AccountTrigger,
    Contribution,
    Exclusion,
    Instrument,
    InstrumentTarget,
    Kill,
    OrderAdjustment,
    Reconciliation,
    ReconciliationStatus,
    RiskAdjustment,
    RiskRule,
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
class RiskEvent(Event):
    """One thing the risk layer did, under one rule (ADR-0033, ADR-0034, ADR-0035).

    The risk gate publishes one for every account rule that reaches its limit at a
    session close, as soon as that close's ``AccountEvent`` arrives, and one for every
    contribution it shrinks or blocks, before the ``ApprovedPortfolioEvent`` that lists
    them all. Execution publishes one for every purchase it cuts to fit the guardrails'
    money caps, before its ``ExecutionPlanEvent``.

    Attributes:
        as_of: The decision time, or for an account rule the close it was measured at.
        profile: The name of the active risk profile.
        adjustment: What happened, under which rule, and why: a ``RiskAdjustment`` (a
            weight, from the gate), an ``OrderAdjustment`` (shares, from execution) or
            an ``AccountTrigger`` (an account rule reached its limit, from the gate).
    """

    as_of: datetime
    profile: str
    adjustment: RiskAdjustment | OrderAdjustment | AccountTrigger

    def __post_init__(self) -> None:
        require_utc(self.as_of, "RiskEvent as_of")
        if not self.profile.strip():
            raise ValueError("RiskEvent: needs the name of the risk profile")


def _require_adjustments(
    targets: tuple[InstrumentTarget, ...], adjustments: tuple[RiskAdjustment, ...]
) -> None:
    """Each sleeve and instrument the gate adjusted ends where its last adjustment says.

    Adjustments to one contribution follow on from each other (each ``before`` is the
    previous ``after``), and the approved weight is the last ``after``: no contribution
    at all after a block.
    """
    last: dict[tuple[str, Instrument], RiskAdjustment] = {}
    for adjustment in adjustments:
        key = (adjustment.strategy_id, adjustment.instrument)
        previous = last.get(key)
        if previous is not None and adjustment.before != previous.after:
            raise ValueError(
                f"ApprovedPortfolioEvent: adjustments of {adjustment.strategy_id} in "
                f"{adjustment.instrument} do not follow on: {previous.after} then "
                f"{adjustment.before}"
            )
        last[key] = adjustment
    by_instrument = {t.instrument: t for t in targets}
    for (strategy_id, instrument), adjustment in last.items():
        target = by_instrument.get(instrument)
        contribution = target.contribution_of(strategy_id) if target else None
        approved = contribution.weight if contribution else Decimal(0)
        if approved != adjustment.after or (contribution is not None and approved == 0):
            raise ValueError(
                f"ApprovedPortfolioEvent: {strategy_id} in {instrument} was adjusted to "
                f"{adjustment.after}, but {approved} is approved"
            )


@dataclass(frozen=True, slots=True)
class ApprovedPortfolioEvent(Event):
    """The portfolio the risk gate approved at one decision time (ADR-0006, ADR-0022).

    The only event execution acts on, and only the risk gate publishes it. It has the
    shape of the ``TargetPortfolioEvent`` it approves, and is read the same way: per
    sleeve and instrument, a contribution gives its weight, ``decided_on`` without one
    gives zero, and anything else the sleeve holds is kept.

    The gate only lowers or removes contributions (ADR-0033). Each change is listed in
    ``adjustments``, in the order the gate made it, and was published as a
    ``RiskEvent`` just before this event.

    Once the drawdown kill has triggered, every approval carries it as ``halt``, with
    no targets and no adjustments, and ``wanted`` keeps everything: execution sends no
    order until a manual restart (ADR-0035).

    While the kill switch is engaged, every approval carries it as ``kill``, with no
    targets and no adjustments (ADR-0039). Without ``flatten``, ``wanted`` keeps
    everything, as under the halt. With ``flatten``, ``wanted`` is zero for every sleeve
    and every instrument, whatever the sleeve decided and even under the halt: execution
    sells every holding.

    While reconciliation has halted trading, every approval carries the mismatch as
    ``unreconciled``, with no targets and no adjustments (ADR-0044). ``wanted`` keeps
    everything, **even when the kill switch asks to flatten**: Tyche's holdings are
    what is in doubt, so a sale sized on them could sell shares the account does not
    hold. Pablo flattens in IBKR's own apps instead.

    Attributes:
        as_of: The decision time.
        sleeves: One per strategy with a budget, ordered by strategy id.
        targets: One per instrument with an approved contribution, ordered by symbol
            and exchange.
        profile: The name of the risk profile the gate applied.
        adjustments: Every change the gate made to the proposal, in order. Empty when
            it approved the proposal as it was.
        halt: The drawdown kill that halted trading, or ``None``.
        kill: The kill switch, if it was engaged at this decision, or ``None``.
        unreconciled: The reconciliation mismatch that halted trading, or ``None``.
    """

    as_of: datetime
    sleeves: tuple[Sleeve, ...]
    targets: tuple[InstrumentTarget, ...]
    profile: str
    adjustments: tuple[RiskAdjustment, ...] = ()
    halt: AccountTrigger | None = None
    kill: Kill | None = None
    unreconciled: Reconciliation | None = None

    def __post_init__(self) -> None:
        _require_portfolio("ApprovedPortfolioEvent", self.as_of, self.sleeves, self.targets)
        if not self.profile.strip():
            raise ValueError("ApprovedPortfolioEvent: needs the name of the risk profile")
        _require_adjustments(self.targets, self.adjustments)
        if self.halt is not None:
            if self.halt.rule is not RiskRule.DRAWDOWN_KILL:
                raise ValueError(
                    f"ApprovedPortfolioEvent: only the drawdown kill halts, not {self.halt.rule}"
                )
            if self.halt.at > self.as_of:
                raise ValueError("ApprovedPortfolioEvent: halted by a trigger after it")
        # A reconciliation halt is not checked against ``as_of``: a paper run reconciles at
        # startup, after the close its decision is about, so it is dated later (ADR-0045).
        unreconciled = self.unreconciled
        if unreconciled is not None and unreconciled.status is not ReconciliationStatus.MISMATCH:
            raise ValueError(
                f"ApprovedPortfolioEvent: a reconciliation {unreconciled.status} does not halt"
            )
        stopped = self.halt is not None or self.kill is not None or self.unreconciled is not None
        if stopped and (self.targets or self.adjustments):
            raise ValueError("ApprovedPortfolioEvent: a halted or killed approval approves nothing")

    @property
    def flattens(self) -> bool:
        """True when the kill switch asks for every holding to be sold (ADR-0039).

        Never under a reconciliation halt (ADR-0044): what Tyche holds is in doubt.
        """
        return self.kill is not None and self.kill.flatten and self.unreconciled is None

    @property
    def keeps_everything(self) -> bool:
        """True when nothing may be traded: halted, unreconciled or killed, and not
        flattening."""
        stopped = self.halt is not None or self.kill is not None or self.unreconciled is not None
        return stopped and not self.flattens

    def sleeve(self, strategy_id: str) -> Sleeve:
        return _sleeve(self.sleeves, strategy_id)

    def wanted(self, strategy_id: str, instrument: Instrument) -> Contribution | Keep | None:
        """How execution reads one sleeve and one instrument (ADR-0022, decision 4).

        Returns ``None`` (a target of zero) for every sleeve, listed or not, and every
        instrument when the kill switch flattens. Otherwise the sleeve's contribution if
        it has one; ``None`` if it decided on the instrument and did not target it;
        ``KEEP`` otherwise (not offered this cycle, the sleeve failed, trading is halted,
        unreconciled or killed): keep what it holds.
        """
        if self.flattens:
            return None
        sleeve = self.sleeve(strategy_id)
        if self.keeps_everything:
            return KEEP
        if sleeve.status is not SleeveStatus.DECIDED or instrument not in sleeve.decided_on:
            return KEEP
        for target in self.targets:
            if target.instrument == instrument:
                return target.contribution_of(strategy_id)
        return None

"""The risk gate (pipeline stage 5): the only publisher of ``ApprovedPortfolioEvent``.

Execution acts on nothing else (ADR-0006), so every order passes through here by
construction. ``RiskGate`` applies the position rules of the active risk profile and
of each strategy's ``[risk]`` table to every proposed portfolio (ADR-0033). It only
ever lowers or removes a contribution, never raises or adds one, and records every
change as a ``RiskAdjustment``, published as a ``RiskEvent``.

The rules, in the order they apply (``review``):

1. **Each contribution on its own.** A strategy's own ``max_position_size`` caps its
   contribution. Then **risk per trade**, on entries and additions that carry a stop:
   the loss from the decision's close to the stop may be at most ``risk_per_trade`` of
   equity, so the weight is at most ``risk_per_trade * close / (close - stop)``. An
   addition is never cut below what the sleeve holds: with a fixed stop, applying it
   to holdings would trim every winner.
2. **Open positions, per sleeve** (a strategy's own ``max_open_positions``), then **for
   the account** (the profile's). What is held and stays held keeps its place; new
   entries fill the free places, largest weight first, ties by symbol and exchange;
   the rest are blocked. A holding the proposal sells to zero frees its place.
3. **Position size, for the account.** The profile's ``max_position_size`` caps each
   instrument across every sleeve, counting what sleeves keep without deciding. Above
   it, every contribution shrinks by the same proportion.

Weights the gate sets are rounded down to ``WEIGHT_PLACES``, so an approved portfolio
never exceeds a limit by a rounding error.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Protocol

from tyche.core.domain import (
    Account,
    Contribution,
    Instrument,
    InstrumentTarget,
    Money,
    RiskAction,
    RiskAdjustment,
    RiskRule,
    RiskScope,
    SleeveStatus,
)
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    Envelope,
    EventBus,
    RiskEvent,
    TargetPortfolioEvent,
)
from tyche.core.risk.limits import RiskLimits

SUBSCRIBER = "risk"

WEIGHT_PLACES = Decimal("1e-12")
"""Weights the gate sets are rounded down to this. A trillionth of equity is far below
one share of anything, so the rounding never changes an order."""

# Enough digits that sums and products of weights are exact before they are rounded
# down: each weight has at most 28 significant digits, the default precision.
_PRECISION = 60

type _Key = tuple[str, Instrument]


class Holdings(Protocol):
    """What each sleeve holds, in shares. ``SleeveBook`` provides it."""

    @property
    def instruments(self) -> tuple[Instrument, ...]:
        """Every instrument some sleeve holds."""
        ...

    def holders(self, instrument: Instrument) -> tuple[str, ...]:
        """The sleeves holding ``instrument``."""
        ...

    def held(self, strategy_id: str, instrument: Instrument) -> Decimal:
        """Shares of ``instrument`` the sleeve holds; zero if none."""
        ...


class RiskGateError(Exception):
    """The gate's inputs broke an assumption it relies on. A bug, not a market event."""


@dataclass(frozen=True, slots=True)
class Review:
    """What the gate approves of one proposed portfolio.

    Attributes:
        targets: The approved targets, in the proposal's order.
        adjustments: Every change made, in the order it was made.
    """

    targets: tuple[InstrumentTarget, ...]
    adjustments: tuple[RiskAdjustment, ...]


def _down(value: Decimal) -> Decimal:
    return value.quantize(WEIGHT_PLACES, rounding=ROUND_FLOOR)


def _up(value: Decimal) -> Decimal:
    return value.quantize(WEIGHT_PLACES, rounding=ROUND_CEILING)


def _by_symbol(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, instrument.exchange


class _Reviewer:
    """One review's working state: each contribution's weight as the rules change it."""

    def __init__(
        self,
        proposed: TargetPortfolioEvent,
        held: Mapping[_Key, Decimal],
        closes: Mapping[Instrument, Money],
        limits: RiskLimits,
    ) -> None:
        self.proposed = proposed
        self.held = held
        self.closes = closes
        self.limits = limits
        self.profile = limits.profile
        self.contributions: dict[_Key, Contribution] = {
            (c.strategy_id, t.instrument): c for t in proposed.targets for c in t.contributions
        }
        self.weights: dict[_Key, Decimal] = {k: c.weight for k, c in self.contributions.items()}
        self.adjustments: list[RiskAdjustment] = []
        self.decided = {
            s.strategy_id: set(s.decided_on)
            for s in proposed.sleeves
            if s.status is SleeveStatus.DECIDED
        }

    # --- reading -------------------------------------------------------------------

    def kept(self, strategy_id: str, instrument: Instrument) -> bool:
        """For a holding: true if the sleeve did not decide on ``instrument``, so keeps it."""
        return instrument not in self.decided.get(strategy_id, set())

    def wants(self, key: _Key) -> bool:
        return self.weights.get(key, Decimal(0)) > 0

    def stays(self, strategy_id: str, instrument: Instrument) -> bool:
        """True if the sleeve holds ``instrument`` and will still hold it after the open."""
        return (strategy_id, instrument) in self.held and (
            self.kept(strategy_id, instrument) or self.wants((strategy_id, instrument))
        )

    def close(self, instrument: Instrument) -> Decimal:
        close = self.closes.get(instrument)
        if close is None:
            raise RiskGateError(f"no closing price seen for {instrument}")
        return close.amount

    # --- changing ------------------------------------------------------------------

    def adjust(
        self, key: _Key, after: Decimal, rule: RiskRule, scope: RiskScope, limit: Decimal, why: str
    ) -> None:
        strategy_id, instrument = key
        self.adjustments.append(
            RiskAdjustment(
                rule=rule,
                scope=scope,
                action=RiskAction.BLOCK if after == 0 else RiskAction.SHRINK,
                strategy_id=strategy_id,
                instrument=instrument,
                before=self.weights[key],
                after=after,
                limit=limit,
                reason=why,
            )
        )
        self.weights[key] = after

    # --- the rules -------------------------------------------------------------------

    def each_contribution(self) -> None:
        for key, contribution in self.contributions.items():
            strategy_id, instrument = key
            own = self.limits.of_strategy(strategy_id)
            cap = own.max_position_size
            if cap is not None and self.weights[key] > cap:
                self.adjust(
                    key,
                    cap,
                    RiskRule.MAX_POSITION_SIZE,
                    RiskScope.STRATEGY,
                    cap,
                    f"{strategy_id}'s own max_position_size is {cap} of equity",
                )
            stop = contribution.stop_price
            holding = self.held.get(key, Decimal(0))
            if stop is None or self.weights[key] <= holding:
                continue  # no stop, or not an entry or addition
            close = self.close(instrument)
            rate = own.risk_per_trade
            if stop.amount < close:
                allowed = _down(min(rate * close / (close - stop.amount), Decimal(1)))
                why = (
                    f"risk per trade {rate}: a stop at {stop.amount} below the close of "
                    f"{close} allows at most {allowed} of equity"
                )
            else:
                allowed = Decimal(0)
                why = (
                    f"the stop at {stop.amount} is not below the close of {close}, so the "
                    "loss to the stop cannot be bounded"
                )
            if holding > allowed:
                allowed = _up(holding)
                why += f"; {strategy_id} already holds {allowed}, which it keeps"
            if self.weights[key] > allowed:
                self.adjust(key, allowed, RiskRule.RISK_PER_TRADE, RiskScope.STRATEGY, rate, why)

    def sleeve_positions(self) -> None:
        for strategy_id in sorted({s for s, _ in self.contributions}):
            limit = self.limits.of_strategy(strategy_id).max_open_positions
            if limit is None:
                continue
            staying = [i for s, i in self.held if s == strategy_id and self.stays(s, i)]
            entries = [
                i
                for s, i in self.contributions
                if s == strategy_id and self.wants((s, i)) and (s, i) not in self.held
            ]
            entries.sort(key=lambda i: (-self.weights[(strategy_id, i)], *_by_symbol(i)))
            free = max(limit - len(staying), 0)
            for rank, instrument in enumerate(entries[free:], start=free + 1):
                self.adjust(
                    (strategy_id, instrument),
                    Decimal(0),
                    RiskRule.MAX_OPEN_POSITIONS,
                    RiskScope.STRATEGY,
                    Decimal(limit),
                    f"{strategy_id}'s own max_open_positions is {limit}: {len(staying)} held "
                    f"stay, leaving {free} for {len(entries)} new entries; this one ranks "
                    f"{rank} by weight",
                )

    def account_positions(self) -> None:
        limit = self.profile.max_open_positions
        held = {i for _, i in self.held}
        staying = {i for s, i in self.held if self.stays(s, i)}
        totals: dict[Instrument, Decimal] = {}
        for (_, instrument), weight in self.weights.items():
            if weight > 0 and instrument not in held:
                totals[instrument] = totals.get(instrument, Decimal(0)) + weight
        entries = sorted(totals, key=lambda i: (-totals[i], *_by_symbol(i)))
        free = max(limit - len(staying), 0)
        for rank, instrument in enumerate(entries[free:], start=free + 1):
            for key in sorted(k for k in self.contributions if k[1] == instrument):
                if self.wants(key):
                    self.adjust(
                        key,
                        Decimal(0),
                        RiskRule.MAX_OPEN_POSITIONS,
                        RiskScope.ACCOUNT,
                        Decimal(limit),
                        f"max_open_positions is {limit}: {len(staying)} held stay, leaving "
                        f"{free} for {len(entries)} new instruments; {instrument} ranks "
                        f"{rank} by weight",
                    )

    def account_sizes(self) -> None:
        cap = self.profile.max_position_size
        for target in self.proposed.targets:
            instrument = target.instrument
            keys = [(c.strategy_id, instrument) for c in target.contributions]
            wanted = [k for k in keys if self.wants(k)]
            total = sum((self.weights[k] for k in wanted), start=Decimal(0))
            kept = sum(
                (w for (s, i), w in self.held.items() if i == instrument and self.kept(s, i)),
                start=Decimal(0),
            )
            if total + kept <= cap:
                continue
            room = _down(max(cap - kept, Decimal(0)))
            why = f"max_position_size is {cap} of equity: {instrument} was proposed at {total}"
            if kept:
                why += f", with {kept} kept by sleeves that did not decide on it"
            why += "; every contribution shrinks by the same proportion"
            for key in wanted:
                self.adjust(
                    key,
                    _down(self.weights[key] * room / total),
                    RiskRule.MAX_POSITION_SIZE,
                    RiskScope.ACCOUNT,
                    cap,
                    why,
                )

    def approved(self) -> tuple[InstrumentTarget, ...]:
        targets: list[InstrumentTarget] = []
        for target in self.proposed.targets:
            contributions = tuple(
                replace(c, weight=self.weights[(c.strategy_id, target.instrument)])
                for c in target.contributions
                if c.weight == 0 or self.wants((c.strategy_id, target.instrument))
            )
            if contributions:
                targets.append(InstrumentTarget(target.instrument, contributions))
        return tuple(targets)


def review(
    proposed: TargetPortfolioEvent,
    held: Mapping[tuple[str, Instrument], Decimal],
    closes: Mapping[Instrument, Money],
    limits: RiskLimits,
) -> Review:
    """Apply the position rules to one proposed portfolio. Pure: no bus, no state.

    Args:
        proposed: The proposal.
        held: What each sleeve holds now, as a weight of account equity above zero,
            by strategy id and instrument. Anything not listed is not held.
        closes: The latest close of every instrument, at least of every one whose
            target carries a stop.
        limits: The guardrails, the active profile and each strategy's own limits.

    Raises:
        RiskGateError: A target with a stop has no closing price.
    """
    with localcontext(prec=_PRECISION, rounding=ROUND_FLOOR):
        reviewer = _Reviewer(proposed, held, closes, limits)
        reviewer.each_contribution()
        reviewer.sleeve_positions()
        reviewer.account_positions()
        reviewer.account_sizes()
        return Review(reviewer.approved(), tuple(reviewer.adjustments))


class RiskGate:
    """Pipeline stage 5. Approves every ``TargetPortfolioEvent``, within the limits.

    Subscribe it after the account state, so that each decision finds the snapshot of
    the same close, as execution does.

    Args:
        bus: The run's event bus.
        limits: The guardrails, the active profile and each strategy's own limits.
        holdings: What each sleeve holds: the sleeve book execution keeps.
    """

    def __init__(self, bus: EventBus, limits: RiskLimits, holdings: Holdings) -> None:
        self._bus = bus
        self._limits = limits
        self._holdings = holdings
        self._account: AccountEvent | None = None
        self._closes: dict[Instrument, Money] = {}
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)
        bus.subscribe(AccountEvent, self._on_account, name=SUBSCRIBER)
        bus.subscribe(TargetPortfolioEvent, self._on_target, name=SUBSCRIBER)

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        bar = envelope.event.bar
        # ``repr`` gives the shortest decimal that round-trips, as execution reads it.
        self._closes[bar.instrument] = Money(Decimal(repr(bar.close)), bar.instrument.currency)

    def _on_account(self, envelope: Envelope[AccountEvent]) -> None:
        self._account = envelope.event

    def _on_target(self, envelope: Envelope[TargetPortfolioEvent]) -> None:
        proposed = envelope.event
        held = self._held(self._snapshot(proposed))
        result = review(proposed, held, self._closes, self._limits)
        name = self._limits.profile.name
        for adjustment in result.adjustments:
            self._bus.publish(RiskEvent(proposed.as_of, name, adjustment))
        self._bus.publish(
            ApprovedPortfolioEvent(
                as_of=proposed.as_of,
                sleeves=proposed.sleeves,
                targets=result.targets,
                profile=name,
                adjustments=result.adjustments,
            )
        )

    def _snapshot(self, proposed: TargetPortfolioEvent) -> Account:
        if self._account is None or self._account.as_of != proposed.as_of:
            seen = self._account.as_of.isoformat() if self._account else "none"
            raise RiskGateError(
                f"the decision at {proposed.as_of.isoformat()} has no account snapshot from "
                f"the same close (latest: {seen})"
            )
        return self._account.account

    def _held(self, account: Account) -> dict[_Key, Decimal]:
        """Each sleeve's holdings as weights of equity, at the latest close."""
        held: dict[_Key, Decimal] = {}
        for instrument in self._holdings.instruments:
            close = self._closes.get(instrument)
            if close is None:
                raise RiskGateError(f"no closing price seen for {instrument}, which is held")
            equity = account.equity(instrument.currency).amount
            if equity <= 0:
                raise RiskGateError(f"equity in {instrument.currency} is {equity}")
            for strategy_id in self._holdings.holders(instrument):
                shares = self._holdings.held(strategy_id, instrument)
                if shares > 0:
                    held[(strategy_id, instrument)] = shares * close.amount / equity
        return held

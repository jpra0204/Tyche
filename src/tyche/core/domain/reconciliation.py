"""Reconciliation's records: the broker's side, and what a comparison found (ADR-0044).

Tyche keeps its own record of the account, the sleeves and the working orders; the
broker keeps its own. Reconciliation (pipeline stage 7) compares the two:

* ``BrokerRecord`` is the broker's side, as ``Broker.record()`` reports it.
* ``Reconciliation`` is what one comparison found: differences, the fills it can
  explain, the orders that ended with no shares moved, and each currency's cash check.
* ``ReconciliationState`` is what the checkpoint remembers between runs: the last
  check, and the halt a mismatch leaves until ``tyche resume`` lifts it.
* ``ReconciliationRules`` holds the market profile's ``[reconciliation]`` table.

The rules, decided with Pablo on 2026-11-24: positions and orders must match exactly;
cash is taken from the broker within a tolerance; anything else halts.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.account import Account, CashBalance
from tyche.core.domain.currency import Currency
from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.order import OrderType, Side


def _require_aware(moment: datetime, what: str) -> None:
    if moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got {moment!r}")


def _one_per_currency(amounts: Iterable[Money], what: str) -> None:
    seen: set[Currency] = set()
    for amount in amounts:
        if amount.currency in seen:
            raise ValueError(f"{what}: {amount.currency} is given twice")
        seen.add(amount.currency)


def _in(amounts: Iterable[Money], currency: Currency) -> Money:
    for amount in amounts:
        if amount.currency is currency:
            return amount
    return Money.zero(currency)


@dataclass(frozen=True, slots=True)
class ReconciliationRules:
    """The market profile's ``[reconciliation]`` table (ADR-0044).

    Attributes:
        cash_tolerance: The cash gap, beyond dividends on their way, that Tyche accepts
            from the broker without halting: fees and interest it does not model. The
            same amount in each of the profile's cash currencies.
    """

    cash_tolerance: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.cash_tolerance, Decimal) or not self.cash_tolerance.is_finite():
            raise ValueError(
                f"cash_tolerance must be a finite decimal, got {self.cash_tolerance!r}"
            )
        if self.cash_tolerance < 0:
            raise ValueError(f"cash_tolerance must not be negative, got {self.cash_tolerance}")

    def tolerance(self, currency: Currency) -> Money:
        return Money(self.cash_tolerance, currency)


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    """One of Tyche's orders that the broker lists as still working.

    Attributes:
        client_order_id: Tyche's id for it.
        remaining: Shares the broker says are still to fill.
    """

    client_order_id: str
    remaining: Decimal

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("a broker order needs a client order id")
        if not self.remaining.is_finite() or self.remaining <= 0:
            raise ValueError(
                f"broker order {self.client_order_id}: remaining must be positive, "
                f"got {self.remaining}"
            )


@dataclass(frozen=True, slots=True)
class BrokerRecord:
    """The broker's own record, as reconciliation compares it (``Broker.record()``).

    Attributes:
        account: The broker's cash, settled and by settlement date, and positions.
        orders: Every Tyche order the broker lists as working, with what remains.
        foreign_orders: Working orders in the account that are not Tyche's.
        accrued_dividends: Dividends the broker has accrued and not paid, per currency.
        unresolved: What the broker adapter could not settle, each in words: an
            execution awaiting its commission, a correction. Any of them halts.
    """

    account: Account
    orders: tuple[BrokerOrder, ...] = ()
    foreign_orders: int = 0
    accrued_dividends: tuple[Money, ...] = ()
    unresolved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = [o.client_order_id for o in self.orders]
        if len(set(ids)) != len(ids):
            raise ValueError("broker record: an order is listed twice")
        if self.foreign_orders < 0:
            raise ValueError("broker record: foreign_orders cannot be negative")
        _one_per_currency(self.accrued_dividends, "broker record: accrued dividends")
        for amount in self.accrued_dividends:
            if amount.is_negative:
                raise ValueError(f"broker record: accrued dividends cannot be negative ({amount})")

    def accrued(self, currency: Currency) -> Money:
        """Dividends accrued and not paid in ``currency``; zero if none reported."""
        return _in(self.accrued_dividends, currency)


class DifferenceKind(StrEnum):
    """What kind of disagreement a ``Difference`` is."""

    POSITION = "position"
    """Tyche and the broker hold different shares of an instrument, unexplained."""

    ORDER = "order"
    """Both list the order as working, with different shares remaining."""

    UNKNOWN_ORDER = "unknown_order"
    """The broker lists one of Tyche's orders as working that Tyche does not expect."""

    FOREIGN_ORDER = "foreign_order"
    """The account has working orders that are not Tyche's."""

    STALE_ORDER = "stale_order"
    """One of Tyche's market orders is still working after the close of the session it
    was sent for, when it should have filled or ended at the open (ADR-0045)."""

    CASH = "cash"
    """The cash gap is larger than the tolerance and the dividends on their way."""

    UNRESOLVED = "unresolved"
    """The broker adapter could not settle something it read."""


@dataclass(frozen=True, slots=True)
class Difference:
    """One disagreement that halts trading.

    Attributes:
        kind: What kind.
        subject: What it is about: an instrument, an order id, a currency.
        detail: Both sides' figures, in words.
    """

    kind: DifferenceKind
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.detail.strip():
            raise ValueError("a difference needs a subject and a detail")

    def __str__(self) -> str:
        return f"{self.kind}: {self.subject}: {self.detail}"


@dataclass(frozen=True, slots=True)
class InferredFill:
    """A fill on a day no run read, inferred from positions and cash (ADR-0044).

    Exactly one of Tyche's working orders, gone from the broker's list, accounts for an
    instrument's difference in shares. Its price is the cash gap divided by the shares,
    commission included, so it is only inferred when no other fill shares that gap.

    Attributes:
        client_order_id: The order that filled.
        instrument: What it traded.
        side: Buy or sell.
        quantity: The shares it still had to fill, all of which did.
        price: The inferred price per share, commission folded in.
    """

    client_order_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    price: Money

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("an inferred fill needs its order's id")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError(f"inferred fill of {self.client_order_id}: quantity must be positive")
        if self.price.currency is not self.instrument.currency or not self.price.is_positive:
            raise ValueError(
                f"inferred fill of {self.client_order_id}: price must be positive, in "
                f"{self.instrument.currency}; got {self.price}"
            )

    def __str__(self) -> str:
        verb = "bought" if self.side is Side.BUY else "sold"
        return (
            f"order {self.client_order_id} {verb} {self.quantity} {self.instrument} "
            f"at about {self.price} on a day no run read"
        )


@dataclass(frozen=True, slots=True)
class EndedOrder:
    """One of Tyche's orders the broker no longer lists, with no shares moved.

    A stop IBKR cancelled by itself, a market-on-open order that did not trade. Tyche
    drops it from its records; a stop still wanted is placed again at the next decision.

    Attributes:
        client_order_id: The order.
        instrument: What it was for.
        order_type: Market or stop.
    """

    client_order_id: str
    instrument: Instrument
    order_type: OrderType

    def __str__(self) -> str:
        return (
            f"{self.order_type} order {self.client_order_id} for {self.instrument} ended unfilled"
        )


class CashOutcome(StrEnum):
    """How one currency's cash check ended."""

    MATCH = "match"
    """No gap."""

    ADOPTED = "adopted"
    """A gap within what is allowed: Tyche takes the broker's figure."""

    PRICED = "priced"
    """The gap priced an inferred fill; applied only by ``tyche resume``."""

    EXCEEDED = "exceeded"
    """A gap beyond what is allowed: a difference."""


@dataclass(frozen=True, slots=True)
class CashCheck:
    """One currency's cash, Tyche's against the broker's (ADR-0044).

    Attributes:
        tyche: Tyche's total cash, settled and pending.
        broker: The broker's cash: settled, and pending by settlement date.
        accrued: Dividends the broker has accrued and not paid.
        allowed: The largest gap accepted: the tolerance plus dividends on their way.
        outcome: How the check ended.
    """

    tyche: Money
    broker: CashBalance
    accrued: Money
    allowed: Money
    outcome: CashOutcome

    def __post_init__(self) -> None:
        currency = self.tyche.currency
        for amount in (self.broker.settled, self.accrued, self.allowed):
            if amount.currency is not currency:
                raise ValueError(f"cash check in {currency}: {amount} is in another currency")
        if self.allowed.is_negative or self.accrued.is_negative:
            raise ValueError(f"cash check in {currency}: allowed and accrued cannot be negative")
        within = abs(self.gap) <= self.allowed
        if self.outcome is CashOutcome.MATCH and not self.gap.is_zero:
            raise ValueError(f"cash check in {currency}: a match has no gap")
        if self.outcome is CashOutcome.ADOPTED and (self.gap.is_zero or not within):
            raise ValueError(f"cash check in {currency}: adopted needs a gap up to {self.allowed}")
        if self.outcome is CashOutcome.EXCEEDED and within:
            raise ValueError(
                f"cash check in {currency}: exceeded needs a gap beyond {self.allowed}"
            )

    @property
    def currency(self) -> Currency:
        return self.tyche.currency

    @property
    def gap(self) -> Money:
        """The broker's cash and accrued dividends, less Tyche's: positive if it has more."""
        return self.broker.total + self.accrued - self.tyche

    @property
    def adopted(self) -> CashBalance:
        """Tyche's cash once it takes the broker's: accrued dividends count as settled."""
        return CashBalance(self.broker.settled + self.accrued, self.broker.pending)

    def __str__(self) -> str:
        return (
            f"{self.currency} cash: Tyche {self.tyche}, broker {self.broker.total} plus "
            f"{self.accrued} accrued dividends; gap {self.gap}, allowed {self.allowed}"
        )


class ReconciliationStatus(StrEnum):
    """What one reconciliation concluded."""

    MATCH = "match"
    """Both records agree."""

    CORRECTED = "corrected"
    """They agree once Tyche takes the broker's cash or drops orders that ended."""

    MISMATCH = "mismatch"
    """They disagree: trading halts until ``tyche resume``."""


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What one comparison of Tyche's records with the broker's found (ADR-0044).

    Attributes:
        at: When it was made.
        differences: Every disagreement nothing explains. Any one halts.
        inferred: Fills on a day no run read that explain a difference. They halt too,
            and ``tyche resume`` applies them.
        ended: Orders the broker no longer lists, with no shares moved.
        cash: One check per currency Tyche trades in.
    """

    at: datetime
    differences: tuple[Difference, ...] = ()
    inferred: tuple[InferredFill, ...] = ()
    ended: tuple[EndedOrder, ...] = ()
    cash: tuple[CashCheck, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.at, "reconciliation time")
        _one_per_currency((c.tyche for c in self.cash), "reconciliation: cash checks")
        ids = [f.client_order_id for f in self.inferred] + [e.client_order_id for e in self.ended]
        if len(set(ids)) != len(ids):
            raise ValueError("reconciliation: an order is both inferred filled and ended, or twice")
        priced = {c.currency for c in self.cash if c.outcome is CashOutcome.PRICED}
        if priced != {f.instrument.currency for f in self.inferred}:
            raise ValueError("reconciliation: each inferred fill prices its currency's cash gap")
        if len(self.inferred) != len(priced):
            raise ValueError("reconciliation: one inferred fill at most per currency")

    @property
    def status(self) -> ReconciliationStatus:
        if self.differences or self.inferred:
            return ReconciliationStatus.MISMATCH
        if self.ended or any(c.outcome is CashOutcome.ADOPTED for c in self.cash):
            return ReconciliationStatus.CORRECTED
        return ReconciliationStatus.MATCH

    def check(self, currency: Currency) -> CashCheck | None:
        """The cash check for ``currency``, or ``None``."""
        for check in self.cash:
            if check.currency is currency:
                return check
        return None


@dataclass(frozen=True, slots=True)
class ReconciliationState:
    """What the checkpoint remembers of reconciliation between runs (ADR-0044).

    Attributes:
        last_at: When the last check that agreed (a match, or corrected) was made, or
            ``None``. Checks that agree while trading is halted count too.
        distributions: Tyche's distributions received to date at that check, per
            currency: what it credits after that is a dividend on its way.
        accrued: The broker's accrued dividends at that check, per currency: what it
            pays after that may arrive net of withholding.
        halt: The latest mismatch while trading is halted, if it is. Only ``tyche
            resume`` lifts it; a check that agrees does not.
    """

    last_at: datetime | None = None
    distributions: tuple[Money, ...] = ()
    accrued: tuple[Money, ...] = ()
    halt: Reconciliation | None = None

    def __post_init__(self) -> None:
        _one_per_currency(self.distributions, "reconciliation memory: distributions")
        _one_per_currency(self.accrued, "reconciliation memory: accrued dividends")
        if self.last_at is None:
            if self.distributions or self.accrued:
                raise ValueError("reconciliation memory: figures without a check")
        else:
            _require_aware(self.last_at, "last reconciliation time")
        if self.halt is not None and self.halt.status is not ReconciliationStatus.MISMATCH:
            raise ValueError(f"reconciliation memory: a {self.halt.status} does not halt")

    @property
    def halt_is_current(self) -> bool:
        """True when no check that agreed came after the halt.

        Then ``tyche resume`` applies what the halt explained. After a check that agreed
        (Pablo fixed the account by hand), Tyche's records already match, and the halt's
        explanations are out of date: resume only lifts it.
        """
        return self.halt is not None and (self.last_at is None or self.halt.at >= self.last_at)

    def distributions_in(self, currency: Currency) -> Money:
        return _in(self.distributions, currency)

    def accrued_in(self, currency: Currency) -> Money:
        return _in(self.accrued, currency)

"""The account ledger: cash per currency, settled and unsettled, and positions.

``Account`` is immutable: every operation returns a new account. That makes each step
easy to test, lets an event carry a snapshot that nothing can change afterwards, and
means a rejected operation leaves the previous account untouched.

Rules the ledger enforces, because Tyche v1 trades a long-only cash account:

* Selling more than is held is refused: that would be a short sale.
* A buy that would take cash below zero, counting unsettled amounts, is refused: that
  would be borrowing. Whether unsettled sale proceeds may be spent is a separate
  broker rule: in a cash account they may not (ADR-0020). ``CashBalance.buying_power``
  says what a cash account can spend; the simulated broker and execution both use it.
* Every fill is applied once.

Positions are valued at their average cost, commissions included. This mirrors the
average-cost method behind Canada's adjusted cost base, but in the instrument's own
currency; the CAD figures for tax come in Phase 4.

Precision: selling part of a position allocates it a share of the cost, which is a
division that may not terminate (selling a third). That share is rounded to
``COST_PLACES`` decimal places, so every amount in the ledger is a finite decimal and
adding them up is exact: cash always equals the deposit plus the realised profit minus
the cost still held, to the last digit. Ten places is far below a cent; tax reports
round to cents at the end.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from tyche.core.domain.corporate_actions import CashDistribution
from tyche.core.domain.costs import CENT_PLACES
from tyche.core.domain.currency import Currency
from tyche.core.domain.fill import Fill
from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.order import Side

COST_PLACES = 10


class LedgerError(ValueError):
    """An operation would break the account's rules. The account is unchanged."""


@dataclass(frozen=True, slots=True)
class Position:
    """Shares held in one instrument.

    Attributes:
        instrument: What is held.
        quantity: How many shares. Always positive; a closed position is removed.
        cost: What they cost in total, commissions included, in the instrument's
            currency.
    """

    instrument: Instrument
    quantity: Decimal
    cost: Money

    def __post_init__(self) -> None:
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError(f"position in {self.instrument}: quantity must be positive")
        if self.cost.currency is not self.instrument.currency:
            raise ValueError(f"position in {self.instrument}: cost must be in its currency")

    @property
    def average_cost(self) -> Money:
        """Cost per share."""
        return self.cost / self.quantity


@dataclass(frozen=True, slots=True)
class PendingCash:
    """Cash from a fill that has not settled yet. Negative for a purchase."""

    amount: Money
    settles_on: date
    fill_id: str


@dataclass(frozen=True, slots=True)
class CashBalance:
    """Cash in one currency.

    Attributes:
        settled: Cash that has settled.
        pending: Amounts from fills still waiting to settle, oldest first.
    """

    settled: Money
    pending: tuple[PendingCash, ...] = ()

    @property
    def unsettled(self) -> Money:
        """The sum of pending amounts: positive if sales are waiting to settle."""
        total = Money.zero(self.settled.currency)
        for item in self.pending:
            total += item.amount
        return total

    @property
    def total(self) -> Money:
        """Settled plus unsettled: the cash the account will have once everything settles."""
        return self.settled + self.unsettled

    def buying_power(self, on: date) -> Money:
        """What a cash account can spend on purchases on session ``on`` (ADR-0020).

        Settled cash as it will be on ``on``, after everything due by then has settled,
        minus every purchase not settled by then: those shares are already bought, and
        their cost is already spent. Sale proceeds count only once they have settled.
        """
        total = self.settled
        for item in self.pending:
            if item.settles_on <= on or item.amount.is_negative:
                total += item.amount
        return total


@dataclass(frozen=True, slots=True)
class Account:
    """A snapshot of the account. Operations return a new snapshot.

    Build one with ``Account.empty()`` and ``deposit``; change it only with
    ``apply_fill``, ``receive_distribution`` (or ``credit``), ``settle`` and ``mark``.
    """

    _settled: Mapping[Currency, Money] = field(default_factory=dict)
    _pending: tuple[PendingCash, ...] = ()
    _positions: Mapping[Instrument, Position] = field(default_factory=dict)
    _marks: Mapping[Instrument, Money] = field(default_factory=dict)
    _realized: Mapping[Currency, Money] = field(default_factory=dict)
    _distributions: Mapping[Currency, Money] = field(default_factory=dict)
    _applied: frozenset[str] = frozenset()

    @classmethod
    def empty(cls) -> Account:
        return cls()

    @classmethod
    def reported(
        cls,
        *,
        settled: Iterable[Money],
        pending: Iterable[PendingCash],
        positions: Iterable[Position],
        marks: Mapping[Instrument, Money],
    ) -> Account:
        """An account as a broker reports it, for comparing with Tyche's own (PR 13).

        Not built from fills: a broker's report is a snapshot, so it carries no realised
        profit, no distributions and no applied fill ids. ``pending`` amounts are what
        the broker says will settle on each date; their ``fill_id`` only labels them.

        Raises:
            LedgerError: a currency's settled cash is given twice, an instrument is held
                twice, or a position has no mark (or a mark has no position, or is not a
                positive price in the instrument's currency).
        """
        settled_by_currency: dict[Currency, Money] = {}
        for amount in settled:
            if amount.currency in settled_by_currency:
                raise LedgerError(f"settled {amount.currency} cash is reported twice")
            settled_by_currency[amount.currency] = amount
        held: dict[Instrument, Position] = {}
        for position in positions:
            if position.instrument in held:
                raise LedgerError(f"{position.instrument} is reported twice")
            held[position.instrument] = position
        if set(marks) != set(held):
            missing = sorted(str(i) for i in set(held) - set(marks))
            extra = sorted(str(i) for i in set(marks) - set(held))
            raise LedgerError(
                f"every position needs one mark: without a mark {missing}, not held {extra}"
            )
        for instrument, price in marks.items():
            if price.currency is not instrument.currency or not price.is_positive:
                raise LedgerError(f"cannot mark {instrument} at {price}")
        return cls(
            _settled=settled_by_currency,
            _pending=tuple(pending),
            _positions=held,
            _marks=dict(marks),
        )

    # --- reading -----------------------------------------------------------------

    def cash(self, currency: Currency) -> CashBalance:
        return CashBalance(
            self._settled.get(currency, Money.zero(currency)),
            tuple(p for p in self._pending if p.amount.currency is currency),
        )

    @property
    def currencies(self) -> tuple[Currency, ...]:
        """Every currency the account has touched, in a fixed order."""
        seen = set(self._settled) | {p.amount.currency for p in self._pending}
        seen |= {i.currency for i in self._positions}
        return tuple(sorted(seen))

    def position(self, instrument: Instrument) -> Position | None:
        return self._positions.get(instrument)

    @property
    def positions(self) -> tuple[Position, ...]:
        """Open positions, ordered by instrument."""
        return tuple(self._positions[i] for i in sorted(self._positions, key=str))

    def mark_of(self, instrument: Instrument) -> Money | None:
        """The last price recorded for a held instrument."""
        return self._marks.get(instrument)

    def market_value(self, currency: Currency) -> Money:
        """Positions in ``currency`` at their last marked price."""
        total = Money.zero(currency)
        for instrument, position in self._positions.items():
            if instrument.currency is currency:
                total += self._marks[instrument] * position.quantity
        return total

    def equity(self, currency: Currency) -> Money:
        """Cash (settled and unsettled) plus market value, in one currency.

        Adding currencies together needs an exchange rate; that comes in Phase 4.
        """
        return self.cash(currency).total + self.market_value(currency)

    def realized_pnl(self, currency: Currency) -> Money:
        """Profit or loss locked in by sales, after commissions on both sides."""
        return self._realized.get(currency, Money.zero(currency))

    def distributions_received(self, currency: Currency) -> Money:
        """Cash distributions credited so far, before any tax withheld."""
        return self._distributions.get(currency, Money.zero(currency))

    # --- changing ------------------------------------------------------------------

    def deposit(self, amount: Money) -> Account:
        """Add settled cash, such as the account's starting balance."""
        if not amount.is_positive:
            raise LedgerError(f"a deposit must be positive, got {amount}")
        return replace(self, _settled=_add(self._settled, amount))

    def apply_fill(self, fill: Fill) -> Account:
        """Record a fill: cash moves to pending, the position changes, the price is marked."""
        if fill.fill_id in self._applied:
            raise LedgerError(f"fill {fill.fill_id} has already been applied")
        account = self._buy(fill) if fill.side is Side.BUY else self._sell(fill)
        pending = (*account._pending, PendingCash(fill.cash_flow, fill.settles_on, fill.fill_id))
        return replace(account, _pending=pending, _applied=self._applied | {fill.fill_id})

    def receive_distribution(self, payment_id: str, amount: Money) -> Account:
        """Credit a cash distribution (a dividend) as settled cash.

        Kept apart from ``deposit`` because a distribution is income and a deposit is
        not: the daily loss limit counts one and excludes the other (ADR-0015).
        ``payment_id`` makes it idempotent, like a fill id.
        """
        if not payment_id.strip():
            raise LedgerError("a distribution needs a payment id")
        if payment_id in self._applied:
            raise LedgerError(f"distribution {payment_id} has already been received")
        if not amount.is_positive:
            raise LedgerError(f"distribution {payment_id}: amount must be positive, got {amount}")
        return replace(
            self,
            _settled=_add(self._settled, amount),
            _distributions=_add(self._distributions, amount),
            _applied=self._applied | {payment_id},
        )

    def credit(self, distribution: CashDistribution) -> Account:
        """Credit what ``distribution`` pays on the shares held now, at its ex-date open.

        Holders at the previous close are paid ``amount_per_share`` times their shares,
        rounded to the cent, as settled cash (ADR-0019). Returns the account unchanged
        if nothing is held or the amount rounds to zero. The simulated broker and
        Tyche's own view of the account both use this, so they cannot disagree.
        """
        held = self.position(distribution.instrument)
        if held is None:
            return self
        amount = (distribution.amount_per_share * held.quantity).round_to(CENT_PLACES)
        if not amount.is_positive:
            return self
        payment_id = (
            f"{distribution.instrument}:{distribution.ex_date.isoformat()}:{distribution.kind}"
        )
        return self.receive_distribution(payment_id, amount)

    def settle(self, through: date) -> Account:
        """Settle every pending amount due on or before ``through``."""
        settled = dict(self._settled)
        remaining: list[PendingCash] = []
        for item in self._pending:
            if item.settles_on <= through:
                settled = dict(_add(settled, item.amount))
            else:
                remaining.append(item)
        return replace(self, _settled=settled, _pending=tuple(remaining))

    def with_cash(self, balance: CashBalance) -> Account:
        """The account with one currency's cash replaced by ``balance``.

        Reconciliation's correction (ADR-0044): Tyche takes the broker's cash, settled
        and by settlement date, within a tolerance. Positions, realised profit and
        distributions received are untouched.
        """
        currency = balance.settled.currency
        for item in balance.pending:
            if item.amount.currency is not currency:
                raise LedgerError(f"{currency} cash cannot hold {item.amount} pending")
        return replace(
            self,
            _settled={**self._settled, currency: balance.settled},
            _pending=(
                *(p for p in self._pending if p.amount.currency is not currency),
                *balance.pending,
            ),
        )

    def mark(self, instrument: Instrument, price: Money) -> Account:
        """Record the latest price of a held instrument, for valuation."""
        if instrument not in self._positions:
            raise LedgerError(f"cannot mark {instrument}: it is not held")
        if price.currency is not instrument.currency or not price.is_positive:
            raise LedgerError(f"cannot mark {instrument} at {price}")
        return replace(self, _marks={**self._marks, instrument: price})

    def _buy(self, fill: Fill) -> Account:
        currency = fill.price.currency
        after = self.cash(currency).total + fill.cash_flow
        if after.is_negative:
            raise LedgerError(
                f"fill {fill.fill_id}: buying {fill.quantity} {fill.instrument} for "
                f"{-fill.cash_flow} would leave {after} in a cash account"
            )
        held = self._positions.get(fill.instrument)
        position = Position(
            fill.instrument,
            fill.quantity + (held.quantity if held else 0),
            fill.gross + fill.commission + (held.cost if held else Money.zero(currency)),
        )
        return replace(
            self,
            _positions={**self._positions, fill.instrument: position},
            _marks={**self._marks, fill.instrument: fill.price},
        )

    def _sell(self, fill: Fill) -> Account:
        held = self._positions.get(fill.instrument)
        if held is None or held.quantity < fill.quantity:
            have = held.quantity if held else 0
            raise LedgerError(
                f"fill {fill.fill_id}: selling {fill.quantity} {fill.instrument} with only "
                f"{have} held would be a short sale"
            )
        cost_sold = (held.cost * fill.quantity / held.quantity).round_to(COST_PLACES)
        realized = _add(self._realized, fill.gross - fill.commission - cost_sold)

        positions = dict(self._positions)
        marks = dict(self._marks)
        left = held.quantity - fill.quantity
        if left == 0:
            del positions[fill.instrument]
            del marks[fill.instrument]
        else:
            positions[fill.instrument] = Position(fill.instrument, left, held.cost - cost_sold)
            marks[fill.instrument] = fill.price
        return replace(self, _positions=positions, _marks=marks, _realized=realized)


def _add(balances: Mapping[Currency, Money], amount: Money) -> Mapping[Currency, Money]:
    current = balances.get(amount.currency, Money.zero(amount.currency))
    return {**balances, amount.currency: current + amount}

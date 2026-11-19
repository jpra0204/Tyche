"""AccountState: Tyche's own view of the account, built from events.

The broker keeps its own record of the account (``Broker.account()``); Tyche keeps
this one, from the same facts the broker reports, so that reconciliation (Phase 2) has
two independent records to compare. Both use the same ledger (``Account``), so the
rules cannot differ.

What changes it, in the order the feed delivers a session:

* the session opens: cash due by that day settles;
* a distribution goes ex: holders at the previous close are credited (``Account.credit``);
* a fill: applied to the ledger;
* the session closes: every held instrument is marked at its latest close, and one
  ``AccountEvent`` is published, before the decision cycle that starts at that close.
"""

from decimal import Decimal

from tyche.core.domain import Account, Instrument, Money
from tyche.core.events import (
    AccountEvent,
    BarEvent,
    DistributionEvent,
    Envelope,
    EventBus,
    FillEvent,
    SessionEvent,
    SessionPhase,
)

SUBSCRIBER = "account"


class AccountState:
    """Keeps Tyche's view of the account and publishes it at every session close.

    Args:
        bus: The run's event bus.
        account: The account at the start, usually ``Account.empty().deposit(...)``.
    """

    def __init__(self, bus: EventBus, account: Account) -> None:
        self._bus = bus
        self._account = account
        self._closes: dict[Instrument, Money] = {}
        bus.subscribe(SessionEvent, self._on_session, name=SUBSCRIBER)
        bus.subscribe(DistributionEvent, self._on_distribution, name=SUBSCRIBER)
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)
        bus.subscribe(FillEvent, self._on_fill, name=SUBSCRIBER)

    @property
    def account(self) -> Account:
        return self._account

    def _on_session(self, envelope: Envelope[SessionEvent]) -> None:
        session = envelope.event.session
        if envelope.event.phase is SessionPhase.OPEN:
            self._account = self._account.settle(session.day)
            return
        for position in self._account.positions:
            instrument = position.instrument
            close = self._closes.get(instrument)
            if instrument.calendar == session.calendar and close is not None:
                self._account = self._account.mark(instrument, close)
        self._bus.publish(AccountEvent(session.closes_at, self._account))

    def _on_distribution(self, envelope: Envelope[DistributionEvent]) -> None:
        self._account = self._account.credit(envelope.event.distribution)

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        bar = envelope.event.bar
        # ``repr`` gives the shortest decimal that round-trips, as the broker reads it.
        self._closes[bar.instrument] = Money(Decimal(repr(bar.close)), bar.instrument.currency)

    def _on_fill(self, envelope: Envelope[FillEvent]) -> None:
        self._account = self._account.apply_fill(envelope.event.fill)

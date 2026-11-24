"""The Broker port: where orders go and fills come from.

A broker talks to the rest of Tyche through events, not method calls:

* it consumes ``OrderEvent`` with status ``SUBMITTED`` (published by execution);
* it consumes ``CancelRequestEvent``: an order still open is cancelled, with the
  request's reason in the note; a request for an order already finished is ignored;
* it publishes every later status of that order as an ``OrderEvent`` (accepted,
  rejected, partially filled, filled, cancelled, expired), with the reason in the
  state's note;
* it publishes a ``FillEvent`` for every execution, just before the order's new status.

An implementation subscribes itself to the bus when it is created, as the journal does.
The protocol below is the part the rest of the core calls directly: the broker's own
record of the account, and the fuller record reconciliation compares with Tyche's own
(ADR-0044): the account, Tyche's orders still working, other working orders, dividends
accrued and not paid, and anything the adapter could not settle.

``SimBroker`` (``tyche.core.sim``) implements it for backtests. ``IBKRBroker``
(``tyche.adapters.brokers.ibkr``) implements it for the paper account (Phase 2, PR 11):
it publishes a sent order's later statuses and fills only once IBKR reports them, when
the paper cycle calls its ``sync``, so a cancellation is confirmed by IBKR, not assumed
(ADR-0042).
"""

from typing import Protocol

from tyche.core.domain import Account, BrokerRecord


class Broker(Protocol):
    """A broker: accepts orders, reports fills, and keeps its own record of the account."""

    def account(self) -> Account:
        """The broker's own record of cash and positions, as of now."""
        ...

    def record(self) -> BrokerRecord:
        """The broker's record for reconciliation, as of now (ADR-0044)."""
        ...

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
record of the account, which reconciliation compares with Tyche's own view
(``AccountState`` in execution) in Phase 2.

``SimBroker`` (``tyche.core.sim``) implements it for backtests; ``IBKRBroker`` in
``tyche.adapters`` will implement it for paper and live trading (Phase 2).
"""

from typing import Protocol

from tyche.core.domain import Account


class Broker(Protocol):
    """A broker: accepts orders, reports fills, and keeps its own record of the account."""

    def account(self) -> Account:
        """The broker's own record of cash and positions, as of now."""
        ...

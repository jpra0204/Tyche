"""The seam between ``IBKRBroker`` and IB Gateway: a small protocol and plain records.

``IBKRBroker`` never touches ``ib_async`` objects. It talks to an ``IBClient``, which
speaks in the records below: plain, immutable, typed, with exact decimals. Two
implementations exist:

* ``IbAsyncClient`` (``ib_async_client.py``) translates them to and from ``ib_async``
  and the gateway; it holds no logic of its own.
* A fake in the tests plays a gateway, so every rule of the adapter is tested without
  a network or an account.

So the vendor's model stays at the edge (an *anti-corruption layer*), and the rules
that matter (identity, idempotency, never resending) are tested against the fake.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import SecretStr


class IBKRError(Exception):
    """Something went wrong talking to IBKR. Messages never include the account id."""


class IBKRConnectionError(IBKRError):
    """No connection to IB Gateway, or it was lost during a request.

    For an order, this means its fate is unknown: it may or may not have reached the
    gateway (ADR-0042).
    """


class IBKRAccountError(IBKRError):
    """The gateway is logged in to an account other than the configured one (ADR-0041)."""


class IBKRContractError(IBKRError):
    """IBKR does not know the instrument, or knows more than one that matches."""


@dataclass(frozen=True, slots=True)
class ContractQuery:
    """A stock or ETF to look up, routed through IBKR's SMART router.

    Attributes:
        symbol: The ticker as IBKR spells it.
        currency: Its currency code, e.g. ``USD``.
        primary_exchange: IBKR's code for its listing exchange, e.g. ``ARCA``, or
            ``None`` to accept any listing as long as only one matches.
    """

    symbol: str
    currency: str
    primary_exchange: str | None


@dataclass(frozen=True, slots=True)
class OrderTicket:
    """One order, exactly as it goes to IBKR (ADR-0041).

    Attributes:
        order_ref: Tyche's client order id, carried in IBKR's ``orderRef``.
        account: The account to place it in.
        contract_id: IBKR's ``conId`` for the instrument.
        action: ``BUY`` or ``SELL``.
        quantity: Whole shares.
        order_type: ``MKT`` or ``STP``.
        time_in_force: ``OPG`` (market on open), ``DAY`` or ``GTC``.
        stop_price: The trigger price, for ``STP`` only.
    """

    order_ref: str
    account: str
    contract_id: int
    action: str
    quantity: int
    order_type: str
    time_in_force: str
    stop_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ReportedOrder:
    """An order as IBKR lists it, open or completed today.

    Attributes:
        order_ref: The ``orderRef`` it carries; Tyche's client order id if it is Tyche's.
        order_id: The API order id.
        perm_id: IBKR's permanent id, 0 if not given.
        account: The account it is in.
        status: IBKR's status word, e.g. ``Submitted`` or ``Cancelled``.
        filled: Shares filled so far.
        remaining: Shares still to fill.
        message: The last error or note IBKR sent about it, empty if none.
    """

    order_ref: str
    order_id: int
    perm_id: int
    account: str
    status: str
    filled: Decimal
    remaining: Decimal
    message: str = ""


@dataclass(frozen=True, slots=True)
class ReportedExecution:
    """One execution as IBKR reports it.

    Attributes:
        exec_id: IBKR's execution id. A correction repeats it with a different ending
            after the last period.
        order_ref: The ``orderRef`` of its order.
        order_id: The API order id of its order.
        perm_id: The permanent id of its order.
        account: The account it is in.
        side: ``BOT`` or ``SLD``.
        shares: Shares that changed hands.
        price: Price per share.
        time: When it happened, timezone-aware.
        commission: Commission and fees from IBKR's report on it, or ``None`` until
            that report has arrived.
        commission_currency: The currency of ``commission``, or ``None``.
    """

    exec_id: str
    order_ref: str
    order_id: int
    perm_id: int
    account: str
    side: str
    shares: Decimal
    price: Decimal
    time: datetime
    commission: Decimal | None
    commission_currency: str | None


@dataclass(frozen=True, slots=True)
class ReportedHolding:
    """A position as IBKR's portfolio lists it.

    Attributes:
        account: The account it is in.
        symbol: The ticker as IBKR spells it.
        currency: Its currency code.
        quantity: Shares held.
        average_cost: IBKR's average cost per share.
        market_price: IBKR's latest price per share.
    """

    account: str
    symbol: str
    currency: str
    quantity: Decimal
    average_cost: Decimal
    market_price: Decimal


@dataclass(frozen=True, slots=True)
class ReportedValue:
    """One account value: a tag, its text and its currency (``BASE`` or a code)."""

    account: str
    tag: str
    value: str
    currency: str


class GatewaySettings(Protocol):
    """Where IB Gateway is, and the one account Tyche may use there.

    ``tyche.config.IbkrConnection``, read from ``.env``, is one; the runtime passes it
    in, so this adapter does not depend on the config package.
    """

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def client_id(self) -> int: ...

    @property
    def account_id(self) -> SecretStr: ...


class IBClient(Protocol):
    """What ``IBKRBroker`` needs from IB Gateway. Every call blocks until it is done.

    A call that cannot reach the gateway raises ``IBKRConnectionError``.
    """

    def connect(self, host: str, port: int, client_id: int, timeout: float) -> None:
        """Connect, and wait until the gateway has sent its accounts and open orders."""
        ...

    def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    def managed_accounts(self) -> tuple[str, ...]:
        """The accounts the gateway's session is logged in to."""
        ...

    def contract_id(self, query: ContractQuery) -> int:
        """IBKR's ``conId`` for the one contract matching ``query``.

        Raises:
            IBKRContractError: none or several match.
        """
        ...

    def place(self, ticket: OrderTicket) -> int:
        """Send a new order; return the API order id it was given.

        Raises:
            IBKRConnectionError: it may or may not have reached the gateway.
        """
        ...

    def cancel(self, order_id: int) -> None:
        """Ask for the order to be cancelled. The answer comes as its status."""
        ...

    def open_orders(self) -> tuple[ReportedOrder, ...]:
        """This client's open orders, read from the gateway now."""
        ...

    def completed_orders(self) -> tuple[ReportedOrder, ...]:
        """Today's API orders that can no longer change, read from the gateway now."""
        ...

    def executions(self, account: str) -> tuple[ReportedExecution, ...]:
        """Today's executions in ``account`` (the gateway keeps no more), read now."""
        ...

    def holdings(self, account: str) -> tuple[ReportedHolding, ...]:
        """Every position in ``account``."""
        ...

    def account_values(self, account: str) -> tuple[ReportedValue, ...]:
        """Every account value IBKR reports for ``account``."""
        ...

"""IBKRBroker: the ``Broker`` port on IB Gateway, for the paper account.

It speaks to the rest of Tyche exactly as ``SimBroker`` does, through events
(``tyche.core.ports.broker``), and to IB Gateway through an ``IBClient``. The rules,
from ADR-0041 (facts) and ADR-0042 (this adapter):

**Identity.** ``connect`` reads the accounts the gateway is logged in to and refuses
to go on unless they are exactly the configured ``IBKR_ACCOUNT_ID``. Nothing is sent
before that check passes. No port, prefix or library default is trusted.

**Sending** (an ``OrderEvent`` with status ``SUBMITTED``):

* A client order id seen before is ignored, so the same decision cannot trade twice.
* Checks a real order must pass, or it is rejected without being sent: whole shares,
  sell stops only, at a price in whole cents, a symbol IBKR spells as Tyche does,
  a known calendar.
* Market orders go as market-on-open (``MKT``, ``OPG``) and stops as ``STP``,
  ``GTC``, regular hours only. ``orderRef`` carries the client order id.
* The order is written to the store, and committed, **before** it is sent. If the
  connection is lost while sending, its fate is unknown: it stays ``SUBMITTED``.

**A sale waits for its stop's cancellation** (decided with Pablo, 2026-11-24, ADR-0045).
A decision publishes a sale before it cancels the stop on the same shares, and IBKR
confirms a cancellation only later. So every new sell order (a market sale or a stop)
is **held**, not sent, when it is published. ``release``, called by the paper cycle
between drains, sends each held order whose instrument has no cancellation still
waiting for IBKR's confirmation. Two orders can then never sell the same shares, which
a cash account cannot do. ``reject_held`` rejects what is still held when the cycle
stops waiting: never sent, so the next decision tries again. Purchases are sent at once.

**Never resend** (decided with Pablo, 2026-11-24). ``sync`` looks for every order
whose fate is unknown in IBKR's open orders, today's completed orders and today's
executions, by ``orderRef``. Found, it is tracked from there. Not found, it is
rejected with a note saying so, and never sent again: the next decision starts from
what the account really holds. A duplicate order is impossible; a missed day is not.

**Reading** (``sync``, called by the paper cycle). Every order Tyche still tracks is
looked up; status changes and new executions are published as ``OrderEvent`` and
``FillEvent``, as the simulator does. An execution waits until IBKR's commission
report for it arrives. What cannot be explained from today's records (an order IBKR
no longer lists, a fill from a day no run read) is reported, never guessed: that is
reconciliation's job (PR 13).

**Deliver, then record.** ``sync`` publishes each event and drains the bus, so every
subscriber has handled it, before the store records it. If a handler fails, the run
saves no checkpoint (ADR-0038), so the next run starts from before the event and must
see it again; recording first would lose it. So ``sync`` is called between drains,
never from a handler, as the engine feeds any outside input.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import pairwise

from tyche.adapters.brokers.ibkr.client import (
    ContractQuery,
    GatewaySettings,
    IBClient,
    IBKRAccountError,
    IBKRConnectionError,
    IBKRContractError,
    IBKRError,
    OrderTicket,
    ReportedExecution,
    ReportedOrder,
)
from tyche.adapters.storage import Fate, SqliteBrokerOrderStore
from tyche.core.domain import (
    Account,
    BrokerOrder,
    BrokerRecord,
    Currency,
    Fill,
    Instrument,
    Money,
    Order,
    OrderState,
    OrderStatus,
    OrderType,
    PendingCash,
    Position,
    Side,
    TimeInForce,
)
from tyche.core.events import CancelRequestEvent, Envelope, EventBus, FillEvent, OrderEvent
from tyche.core.ports import Calendar, Clock
from tyche.core.sim import settlement_date

SUBSCRIBER = "ibkr-broker"

PRIMARY_EXCHANGES: Mapping[str, str] = {"ARCX": "ARCA"}
"""IBKR's code for a listing exchange, by its MIC: only the codes checked in IBKR's
documentation (2026-11-24: the TWS API *Stocks* page gives ``ARCA`` for SPY). A listing
not here is looked up without one, and must then match exactly one contract."""

ACCRUED_DIVIDEND_TAG = "AccruedDividend"
"""Dividends accrued and not paid (TWS API, *Account Updates*, read 2026-11-24). Which
currencies it is reported in, and whether net of withholding, is not documented: a
paper-account check (ADR-0044)."""

SETTLED_CASH_TAG = "SettledCashByDate"
"""The account value that gives settled cash now and by settlement date, per currency
(TWS API, *Account Updates*, read 2026-11-24)."""

_SYMBOL = re.compile(r"[A-Z0-9]+")
"""Symbols IBKR is known to spell as Tyche does. ``BRK.B`` and the like are refused
until IBKR's spelling of them is checked."""

_CENT = Decimal("0.01")

_WAITING = frozenset({"PendingSubmit", "ApiPending"})
_WORKING = frozenset({"PreSubmitted", "Submitted", "PendingCancel", "PreCancelled", "ApiUpdate"})
_ENDED_UNFILLED = frozenset({"Cancelled", "ApiCancelled", "Inactive"})
_FILLED = "Filled"

log = logging.getLogger(__name__)


class OpenOrderStyle(StrEnum):
    """How an order for the next open is sent (ADR-0041, decision 2)."""

    MARKET_ON_OPEN = "OPG"
    """``MKT`` with time in force ``OPG``: joins the opening auction. The default."""

    DAY = "DAY"
    """A day market order: active after the opening print. The fallback if paper
    shows market-on-open orders refused."""


class IBKRBrokerError(IBKRError):
    """IBKR's records and Tyche's disagree in a way that must stop the run."""


@dataclass(frozen=True, slots=True)
class _Held:
    """A sell order published and checked, waiting to be sent (ADR-0045)."""

    state: OrderState
    contract_id: int


@dataclass(frozen=True, slots=True)
class Unaccounted:
    """An order whose fate today's records do not explain. Reconciliation decides."""

    client_order_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What one ``sync`` could not settle by itself.

    Attributes:
        lost: Orders sent with an unknown fate and not found at IBKR: now rejected,
            never resent.
        unaccounted: Orders today's records do not explain.
        awaiting_commission: Executions held back until IBKR reports their commission.
        corrections: Executions that correct one already published: not applied.
        foreign_executions: Executions in the account that are not Tyche's orders.
    """

    lost: tuple[str, ...] = ()
    unaccounted: tuple[Unaccounted, ...] = ()
    awaiting_commission: tuple[str, ...] = ()
    corrections: tuple[str, ...] = ()
    foreign_executions: int = 0

    @property
    def clean(self) -> bool:
        """True when every order Tyche tracks is explained by today's records."""
        return not (self.lost or self.unaccounted or self.awaiting_commission or self.corrections)


class IBKRBroker:
    """The paper broker. Implements the ``Broker`` port.

    Build it before anything is published (it subscribes to the bus), then call
    ``connect`` before the run publishes its first order.

    Args:
        bus: The run's event bus.
        client: The connection to IB Gateway.
        store: The adapter's memory of what it sent, in the state database.
        connection: Host, port, client id and the one account it may use.
        instruments: Every instrument Tyche may trade or hold: IBKR's positions are
            matched to these.
        calendars: A calendar for every calendar code they use.
        settlement_days: Sessions to settlement, as in the costs file (ADR-0020).
        clock: The wall clock.
        open_orders: How orders for the next open are sent.
        timeout: Seconds to wait for the gateway when connecting.
    """

    def __init__(
        self,
        bus: EventBus,
        client: IBClient,
        store: SqliteBrokerOrderStore,
        *,
        connection: GatewaySettings,
        instruments: Iterable[Instrument],
        calendars: Mapping[str, Calendar],
        settlement_days: int,
        clock: Clock,
        open_orders: OpenOrderStyle = OpenOrderStyle.MARKET_ON_OPEN,
        timeout: float = 10.0,
    ) -> None:
        if connection.client_id <= 0:
            raise IBKRError("client id 0 would merge Pablo's own orders with Tyche's (ADR-0041)")
        self._bus = bus
        self._client = client
        self._store = store
        self._connection = connection
        self._account = connection.account_id.get_secret_value()
        self._instruments = {(i.symbol, i.currency.value): i for i in instruments}
        self._calendars = dict(calendars)
        self._settlement_days = settlement_days
        self._clock = clock
        self._open_orders = open_orders
        self._timeout = timeout

        self._verified = False
        self._contracts: dict[Instrument, int] = {}
        self._seen: set[str] = set()
        self._unsent: set[str] = set()
        self._duplicates: list[str] = []
        self._held: dict[str, _Held] = {}
        self._report = SyncReport()

        bus.subscribe(OrderEvent, self._on_order, name=SUBSCRIBER)
        bus.subscribe(CancelRequestEvent, self._on_cancel, name=SUBSCRIBER)

    # --- connection -----------------------------------------------------------------

    def connect(self) -> None:
        """Connect to IB Gateway and check it is logged in to the configured account only.

        Raises:
            IBKRConnectionError: the gateway cannot be reached.
            IBKRAccountError: it is logged in to any other account, or to more than one.
                The connection is closed again.
        """
        c = self._connection
        self._verified = False
        self._client.connect(c.host, c.port, c.client_id, self._timeout)
        accounts = self._client.managed_accounts()
        if accounts != (self._account,):
            self._client.disconnect()
            raise IBKRAccountError(
                f"IB Gateway is logged in to {len(accounts)} account(s), not exactly the one "
                "in IBKR_ACCOUNT_ID; refusing to trade (account ids not shown; ADR-0041)"
            )
        self._verified = True

    def close(self) -> None:
        """Disconnect. Orders already sent keep working at IBKR."""
        self._verified = False
        self._client.disconnect()

    @property
    def connected(self) -> bool:
        """Connected, and to the configured account."""
        return self._verified and self._client.is_connected()

    # --- the Broker port ------------------------------------------------------------

    def account(self) -> Account:
        """IBKR's own record of the account: settled cash by date, and positions.

        Raises:
            IBKRBrokerError: IBKR reports no settled cash by date, holds an instrument
                Tyche does not know, or gives no price for a position.
        """
        self._require_connection()
        settled: list[Money] = []
        pending: list[PendingCash] = []
        for value in self._client.account_values(self._account):
            if value.tag != SETTLED_CASH_TAG or value.currency == "BASE":
                continue
            now, later = _settled_cash_by_date(value.value, _currency(value.currency))
            settled.append(now)
            pending.extend(later)
        if not settled:
            raise IBKRBrokerError(
                f"IBKR reported no {SETTLED_CASH_TAG}, so settled cash cannot be told from "
                "unsettled (ADR-0042)"
            )
        positions: list[Position] = []
        marks: dict[Instrument, Money] = {}
        for holding in self._client.holdings(self._account):
            if holding.quantity == 0:
                continue
            instrument = self._instruments.get((holding.symbol, holding.currency))
            if instrument is None:
                raise IBKRBrokerError(
                    f"the account holds {holding.quantity} {holding.symbol} "
                    f"({holding.currency}), which is not one of Tyche's instruments"
                )
            if holding.market_price <= 0:
                raise IBKRBrokerError(f"IBKR gives no price for {instrument}")
            currency = instrument.currency
            positions.append(
                Position(
                    instrument,
                    holding.quantity,
                    Money(holding.average_cost * holding.quantity, currency),
                )
            )
            marks[instrument] = Money(holding.market_price, currency)
        return Account.reported(settled=settled, pending=pending, positions=positions, marks=marks)

    # --- what the paper cycle and reconciliation read ---------------------------------

    @property
    def ignored_duplicates(self) -> tuple[str, ...]:
        """Client order ids submitted more than once; the repeats were ignored."""
        return tuple(self._duplicates)

    @property
    def last_report(self) -> SyncReport:
        """What the last ``sync`` could not settle by itself."""
        return self._report

    def order(self, client_order_id: str) -> OrderState | None:
        """The latest state of an order this adapter sent."""
        record = self._store.get(client_order_id)
        return record.state if record else None

    def sync(self) -> SyncReport:
        """Read IBKR's orders and today's executions, and deliver what changed.

        Call it between drains, never from a handler: it drains the bus after each event.

        Raises:
            IBKRConnectionError: not connected to the configured account.
            IBKRBrokerError: an execution contradicts the order it belongs to.
        """
        self._require_connection()
        now = self._clock.now()
        listed: dict[str, ReportedOrder] = {}
        for item in (*self._client.completed_orders(), *self._client.open_orders()):
            if item.order_ref and item.account in ("", self._account):
                listed[item.order_ref] = item  # open orders win: read last
        executions: dict[str, list[ReportedExecution]] = defaultdict(list)
        for execution in self._client.executions(self._account):
            executions[execution.order_ref].append(execution)

        known = {r.client_order_id for r in self._store.all()}
        foreign = sum(len(found) for ref, found in executions.items() if ref not in known)
        applied = {_base(exec_id) for exec_id in self._store.fills()}
        lost: list[str] = []
        unaccounted: list[Unaccounted] = []
        awaiting: list[str] = []
        corrections: list[str] = []

        for record in self._store.unfinished():
            order_id = record.client_order_id
            reported = listed.get(order_id)
            found = sorted(executions.get(order_id, ()), key=lambda e: (e.time, e.exec_id))
            if reported is None and not found:
                if record.fate is Fate.SENDING:
                    lost.append(order_id)
                    note = (
                        "lost: the connection to IB Gateway dropped while sending, and IBKR "
                        "lists it neither open, nor completed today, nor executed today; "
                        "never resent (ADR-0042)"
                    )
                    self._deliver(OrderEvent(record.state.reject(note)))
                    self._store.record_lost(order_id, record.state.reject(note), now)
                else:
                    unaccounted.append(
                        Unaccounted(
                            order_id,
                            "IBKR lists it neither open nor completed today, and it has no "
                            "execution today",
                        )
                    )
                continue

            if record.fate is Fate.SENDING:
                ids = reported.order_id if reported else found[0].order_id
                self._store.record_placed(order_id, ids, now)
            perm_id = reported.perm_id if reported else found[0].perm_id
            if perm_id > 0 and record.perm_id != perm_id:
                self._store.record_perm_id(order_id, perm_id, now)

            state = record.state
            status = reported.status if reported else ""
            if status and status not in _WAITING | _WORKING | _ENDED_UNFILLED | {_FILLED}:
                unaccounted.append(Unaccounted(order_id, f"unknown IBKR status {status!r}"))
                continue
            at_ibkr = bool(found) or status in _WORKING or status == _FILLED
            if state.status is OrderStatus.SUBMITTED and at_ibkr:
                state = self._publish(state.accept(), now)

            blocked = False
            for execution in found:
                if self._store.fill_seen(execution.exec_id):
                    continue
                if _base(execution.exec_id) in applied:
                    corrections.append(execution.exec_id)
                    blocked = True
                    continue
                if execution.commission is None:
                    awaiting.append(execution.exec_id)
                    blocked = True
                    break
                fill = self._fill(state.order, execution)
                if fill.quantity > state.remaining:
                    raise IBKRBrokerError(
                        f"execution {execution.exec_id} fills {fill.quantity} of order "
                        f"{order_id}, which has only {state.remaining} left"
                    )
                self._deliver(FillEvent(fill))
                self._store.record_fill(execution.exec_id, order_id, now)
                applied.add(_base(execution.exec_id))
                state = self._publish(state.fill(fill.quantity), now)
            if blocked or reported is None:
                continue

            if status in _ENDED_UNFILLED and not state.status.is_terminal:
                note = f"IBKR: {status}" + (f": {reported.message}" if reported.message else "")
                if state.status is OrderStatus.SUBMITTED and not record.cancel_requested:
                    state = self._publish(state.reject(note), now)  # it never worked
                else:
                    if state.status is OrderStatus.SUBMITTED:
                        state = self._publish(state.accept(), now)  # cancelled as asked
                    state = self._publish(state.cancel(note), now)
            elif status == _FILLED and state.status is not OrderStatus.FILLED:
                unaccounted.append(
                    Unaccounted(
                        order_id,
                        f"IBKR says filled, but today's executions cover "
                        f"{state.filled_quantity} of {state.order.quantity} shares",
                    )
                )
            elif record.cancel_requested and status in _WORKING and reported.order_id > 0:
                self._client.cancel(reported.order_id)  # asked before; ask again

        self._report = SyncReport(
            lost=tuple(lost),
            unaccounted=tuple(unaccounted),
            awaiting_commission=tuple(awaiting),
            corrections=tuple(corrections),
            foreign_executions=foreign,
        )
        return self._report

    def record(self) -> BrokerRecord:
        """IBKR's record for reconciliation (ADR-0044): call it after ``sync``.

        The account as ``account()`` reads it; every Tyche order IBKR lists as working,
        with its remaining shares; the count of other working orders in the account;
        ``AccruedDividend`` per currency; and what the last ``sync`` could not settle
        (executions awaiting a commission, corrections).

        Raises:
            IBKRBrokerError: as ``account()``, or IBKR reports an accrued dividend
                Tyche cannot read.
        """
        account = self.account()
        known = {r.client_order_id for r in self._store.all()}
        orders: list[BrokerOrder] = []
        foreign = 0
        unresolved: list[str] = []
        for item in self._client.open_orders():
            if item.account not in ("", self._account):
                continue
            if item.order_ref not in known:
                foreign += 1
            elif item.status not in _WAITING | _WORKING:
                unresolved.append(
                    f"IBKR lists order {item.order_ref} as open with status {item.status!r}"
                )
            elif item.remaining > 0:
                orders.append(BrokerOrder(item.order_ref, item.remaining))
        unresolved.extend(
            f"execution {e} awaits IBKR's commission report"
            for e in self._report.awaiting_commission
        )
        unresolved.extend(
            f"execution {e} corrects one already applied" for e in self._report.corrections
        )
        try:
            return BrokerRecord(
                account=account,
                orders=tuple(sorted(orders, key=lambda o: o.client_order_id)),
                foreign_orders=foreign,
                accrued_dividends=self._accrued(),
                unresolved=tuple(unresolved),
            )
        except ValueError as error:
            raise IBKRBrokerError(f"IBKR's record cannot be read: {error}") from error

    def _accrued(self) -> tuple[Money, ...]:
        accrued: list[Money] = []
        for value in self._client.account_values(self._account):
            if value.tag != ACCRUED_DIVIDEND_TAG or value.currency == "BASE":
                continue
            try:
                amount = Decimal(value.value)
            except InvalidOperation as error:
                raise IBKRBrokerError(
                    f"cannot read {ACCRUED_DIVIDEND_TAG} {value.value!r}"
                ) from error
            if not amount.is_finite():
                raise IBKRBrokerError(f"{ACCRUED_DIVIDEND_TAG} in {value.currency} is not a number")
            if amount != 0:
                accrued.append(Money(amount, _currency(value.currency)))
        return tuple(accrued)

    # --- handlers -------------------------------------------------------------------

    def _on_order(self, envelope: Envelope[OrderEvent]) -> None:
        state = envelope.event.state
        if state.status is not OrderStatus.SUBMITTED:
            return  # every later status is the broker's own
        order = state.order
        order_id = order.client_order_id
        if order_id in self._seen or self._store.get(order_id) is not None:
            self._duplicates.append(order_id)
            return
        self._seen.add(order_id)

        reason = self._rejection(order)
        if not reason and not self.connected:
            reason = "not sent: no connection to IB Gateway on the configured account"
        contract_id = 0
        if not reason:
            try:
                contract_id = self._contract_id(order.instrument)
            except IBKRContractError as error:
                reason = f"not sent: {error}"
            except IBKRConnectionError:
                reason = "not sent: the connection to IB Gateway dropped looking up the contract"
        if reason:
            self._unsent.add(order_id)
            self._bus.publish(OrderEvent(state.reject(reason)))
            return
        if order.side is Side.SELL:
            self._held[order_id] = _Held(state, contract_id)  # sent by release()
            return
        self._send(state, contract_id)

    def _on_cancel(self, envelope: Envelope[CancelRequestEvent]) -> None:
        order_id = envelope.event.client_order_id
        held = self._held.pop(order_id, None)
        if held is not None:
            self._unsent.add(order_id)
            self._bus.publish(OrderEvent(held.state.reject("not sent: cancelled while held")))
            return
        record = self._store.get(order_id)
        if record is None:
            if order_id in self._unsent:
                return  # rejected before it was sent; nothing to cancel
            raise IBKRBrokerError(f"cancel requested for order {order_id}, which was never sent")
        if record.state.status.is_terminal:
            return  # it finished first; nothing left to cancel
        self._store.request_cancel(order_id, self._clock.now())
        if record.fate is Fate.PLACED and record.order_id is not None and self.connected:
            try:
                self._client.cancel(record.order_id)
            except IBKRConnectionError:
                log.warning("cancel of order %s not sent; the next sync asks again", order_id)

    # --- sending held orders (ADR-0045) ---------------------------------------------

    @property
    def held(self) -> tuple[str, ...]:
        """Sell orders published and not yet sent, oldest first."""
        return tuple(self._held)

    def release(self) -> tuple[str, ...]:
        """Send each held sell order whose instrument has no cancellation still waiting
        for IBKR's confirmation. Returns the orders still held.

        Call it between drains, after ``sync``, which reads the confirmations.

        Raises:
            IBKRConnectionError: not connected to the configured account.
        """
        self._require_connection()
        cancelling = {
            r.state.order.instrument for r in self._store.unfinished() if r.cancel_requested
        }
        for order_id, held in list(self._held.items()):
            if held.state.order.instrument in cancelling:
                continue
            del self._held[order_id]
            self._send(held.state, held.contract_id)
        return self.held

    def reject_held(self, reason: str) -> tuple[str, ...]:
        """Reject every order still held, never sent, and deliver each rejection.

        Call it between drains. Returns the orders rejected.
        """
        rejected = self.held
        for order_id in rejected:
            held = self._held.pop(order_id)
            self._unsent.add(order_id)
            self._deliver(OrderEvent(held.state.reject(f"not sent: {reason}")))
        return rejected

    def forget(self, order_ids: Iterable[str], note: str) -> tuple[str, ...]:
        """Close the store's records of orders Tyche no longer tracks. Returns those closed.

        An order IBKR stopped listing is ``unaccounted`` at every ``sync`` until
        reconciliation drops it from Tyche's records (ended, or a missed fill applied by
        ``tyche resume``, ADR-0044). The paper cycle then forgets it here, so it is not
        reported again and no sale waits on its cancellation. Nothing is published:
        Tyche's records already say how it ended.
        """
        now = self._clock.now()
        closed: list[str] = []
        for order_id in sorted(set(order_ids)):
            record = self._store.get(order_id)
            if record is None or record.state.status.is_terminal:
                continue
            state = record.state
            if state.status is OrderStatus.SUBMITTED:
                state = state.reject(note)
            else:
                state = state.cancel(note)
            self._store.record_state(state, now)
            closed.append(order_id)
        return tuple(closed)

    # --- helpers --------------------------------------------------------------------

    def _send(self, state: OrderState, contract_id: int) -> None:
        """Write the order to the store, committed, then send it, once."""
        order_id = state.order.client_order_id
        now = self._clock.now()
        self._store.record_sending(state, now)  # committed before it leaves Tyche
        try:
            broker_id = self._client.place(self._ticket(state.order, contract_id))
        except IBKRConnectionError:
            log.warning(
                "order %s may or may not have reached IB Gateway; the next sync looks for "
                "it and never resends it",
                order_id,
            )
            return
        self._store.record_placed(order_id, broker_id, now)

    def _rejection(self, order: Order) -> str:
        if not _SYMBOL.fullmatch(order.instrument.symbol):
            return (
                f"not sent: IBKR's spelling of {order.instrument.symbol} has not been checked; "
                "only letters and digits are sent"
            )
        if order.instrument.calendar not in self._calendars:
            return f"not sent: no calendar loaded for {order.instrument.calendar}"
        if order.quantity != order.quantity.to_integral_value():
            return f"not sent: whole shares only, cannot trade {order.quantity} (ADR-0020)"
        if order.order_type is OrderType.STOP:
            if order.side is Side.BUY:
                return "not sent: buy stops are not supported: Tyche is long-only"
            if order.time_in_force is not TimeInForce.GTC:
                return "not sent: a protective stop rests good-till-cancelled (ADR-0041)"
            stop = order.stop_price
            if stop is not None and stop.amount != stop.amount.quantize(_CENT):
                return f"not sent: stop price {stop} is not in whole cents; IBKR would refuse it"
        elif order.time_in_force is not TimeInForce.DAY:
            return "not sent: a market order is for the next open only (ADR-0041)"
        return ""

    def _contract_id(self, instrument: Instrument) -> int:
        if instrument not in self._contracts:
            query = ContractQuery(
                symbol=instrument.symbol,
                currency=instrument.currency.value,
                primary_exchange=PRIMARY_EXCHANGES.get(instrument.exchange),
            )
            self._contracts[instrument] = self._client.contract_id(query)
        return self._contracts[instrument]

    def _ticket(self, order: Order, contract_id: int) -> OrderTicket:
        action = "BUY" if order.side is Side.BUY else "SELL"
        if order.order_type is OrderType.STOP:
            if order.stop_price is None:  # pragma: no cover - Order guarantees a stop price
                raise IBKRBrokerError(f"stop order {order.client_order_id} has no stop price")
            return OrderTicket(
                order_ref=order.client_order_id,
                account=self._account,
                contract_id=contract_id,
                action=action,
                quantity=int(order.quantity),
                order_type="STP",
                time_in_force="GTC",
                stop_price=order.stop_price.amount,
            )
        return OrderTicket(
            order_ref=order.client_order_id,
            account=self._account,
            contract_id=contract_id,
            action=action,
            quantity=int(order.quantity),
            order_type="MKT",
            time_in_force=self._open_orders.value,
        )

    def _fill(self, order: Order, execution: ReportedExecution) -> Fill:
        instrument = order.instrument
        label = f"execution {execution.exec_id} of order {order.client_order_id}"
        expected_side = "BOT" if order.side is Side.BUY else "SLD"
        if execution.side != expected_side:
            raise IBKRBrokerError(f"{label} is {execution.side}, the order is a {order.side}")
        if execution.commission_currency != instrument.currency.value:
            raise IBKRBrokerError(
                f"{label}: commission in {execution.commission_currency}, the trade is in "
                f"{instrument.currency}; a fill's costs must be in its own currency for now"
            )
        if execution.time.tzinfo is None:
            raise IBKRBrokerError(f"{label} has a time with no time zone")
        filled_at = execution.time.astimezone(UTC)
        calendar = self._calendars[instrument.calendar]
        session = calendar.session_on(filled_at.date())
        if session is None or not session.opens_at <= filled_at <= session.closes_at:
            raise IBKRBrokerError(
                f"{label} at {filled_at.isoformat()} is outside a {calendar.mic} session"
            )
        commission = execution.commission
        if commission is None:  # pragma: no cover - sync holds these back
            raise IBKRBrokerError(f"{label} has no commission yet")
        return Fill(
            fill_id=f"ibkr-{execution.exec_id}",
            client_order_id=order.client_order_id,
            instrument=instrument,
            side=order.side,
            quantity=execution.shares,
            price=Money(execution.price, instrument.currency),
            commission=Money(abs(commission), instrument.currency),
            filled_at=filled_at,
            trade_date=session.day,
            settles_on=settlement_date(session.day, self._settlement_days, calendar),
        )

    def _publish(self, state: OrderState, at: datetime) -> OrderState:
        self._deliver(OrderEvent(state))
        self._store.record_state(state, at)
        return state

    def _deliver(self, event: OrderEvent | FillEvent) -> None:
        """Publish ``event`` and let every subscriber handle it, before it is recorded."""
        self._bus.publish(event, source=SUBSCRIBER)
        self._bus.drain()

    def _require_connection(self) -> None:
        if not self.connected:
            raise IBKRConnectionError(
                "not connected to IB Gateway on the configured account; call connect() first"
            )


def _base(exec_id: str) -> str:
    """An execution id without its last part, which a correction changes."""
    return exec_id.rsplit(".", 1)[0]


def _currency(code: str) -> Currency:
    try:
        return Currency(code)
    except ValueError as error:
        raise IBKRBrokerError(f"IBKR reports cash in {code}, which Tyche does not know") from error


def _settled_cash_by_date(text: str, currency: Currency) -> tuple[Money, list[PendingCash]]:
    """Settled cash now, and what settles on each later date, from ``SettledCashByDate``.

    The text is ``YYYYMMDD:value`` pairs joined by semicolons. The first is the cash
    settled now; each later value is cumulative, so what settles on that date is its
    difference from the one before (TWS API, *Account Updates*).
    """
    entries: list[tuple[date, Decimal]] = []
    for part in text.split(";"):
        day_text, _, amount_text = part.strip().partition(":")
        try:
            day = datetime.strptime(day_text, "%Y%m%d").date()  # noqa: DTZ007 - a date only
            amount = Decimal(amount_text)
        except (ValueError, InvalidOperation) as error:
            raise IBKRBrokerError(
                f"cannot read {SETTLED_CASH_TAG} entry {part!r} for {currency}"
            ) from error
        if not amount.is_finite():
            raise IBKRBrokerError(f"{SETTLED_CASH_TAG} for {currency} is not a number")
        entries.append((day, amount))
    days = [day for day, _ in entries]
    if not entries or days != sorted(set(days)):
        raise IBKRBrokerError(f"{SETTLED_CASH_TAG} for {currency} is not in date order")
    pending: list[PendingCash] = []
    for (_, before), (day, after) in pairwise(entries):
        if after != before:
            label = f"ibkr-settles-{currency}-{day.isoformat()}"
            pending.append(PendingCash(Money(after - before, currency), day, label))
    return Money(entries[0][1], currency), pending

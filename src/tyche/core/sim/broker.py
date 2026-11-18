"""SimBroker: the simulated broker used in backtests.

It implements the ``Broker`` port: it takes submitted orders from the bus, fills them
against daily bars, and keeps its own record of the account, as IBKR does for a real
one. Every rule below is a model of a real broker, and every report must say so
(ADR-0005: parity of code, not of markets).

**When orders work.** An accepted order starts working at the next open of its
instrument's calendar. Tyche decides after the close, so an order decided at the close
of session *t* works in session *t+1*. A day order still open at that session's close
expires; a good-till-cancelled stop keeps working.

**Checks at submission** (a failure is a rejection, with the reason in the note):

* the order is in the currency the costs are charged in;
* the quantity is whole shares (ADR-0020: IBKR's API cannot place fractions);
* a stop is a sell: Tyche is long-only, so a buy stop has no use;
* a sale is for no more shares than are held.

A ``client_order_id`` the broker has already seen is ignored, so sending the same
decision twice cannot trade twice. Ignored ids are listed in ``ignored_duplicates``.

**Fills** (the bar for a session arrives at its close, with that session's prices):

* A market order fills at the bar's open.
* A sell stop that the open has already gone through fills at the open. Otherwise,
  if the bar's low reaches the stop, it fills at the stop price. A daily bar does not
  say when the low happened, so a stop is assumed to fill whenever the low reaches it:
  the pessimistic reading (ADR-0006).
* Slippage moves every fill price against the order (ADR-0020).
* One bar can fill at most ``max_volume_participation`` of its volume across all of an
  instrument's orders. The rest of a day order expires at the close: a partial fill.
* A purchase is paid from settled cash only (ADR-0020). If settled cash cannot pay for
  the whole order at the open, including costs, the order is cancelled, not shrunk.
* A sale for more shares than are held when it fills is cancelled.
* Commission and regulatory fees are charged per fill (``TradingCosts.cost_of``) and
  recorded as the fill's commission.
* A trade settles ``settlement_days`` sessions later on the instrument's calendar.
  Pending cash settles at the open of its settlement date.

**Free riding.** Selling shares before their purchase has settled is executed, as a
real broker would, and recorded in ``free_riding`` (ADR-0020). Purchases are matched to
sales oldest first.

**Distributions.** At the open of an ex-date, holders at the previous close are
credited ``amount_per_share`` times their shares, rounded to the cent, as settled
cash. The payment date is not known, so this is early by days or weeks (ADR-0019), and
no withholding tax is deducted yet (Phase 2 or 4). Both make income look slightly
better than it is.

**Known limit: splits.** Prices and volumes are split-adjusted, so before a split the
simulation holds and trades split-adjusted shares. Whole-share sizing is then applied
to adjusted shares, which can allow a position the real account could not have bought
before the split (one adjusted share may be a tenth of a real one).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal

from tyche.core.domain import (
    Account,
    Bar,
    Fill,
    Instrument,
    Money,
    OrderState,
    OrderStatus,
    OrderType,
    Session,
    Side,
    TimeInForce,
    TradingCosts,
)
from tyche.core.domain.costs import CENT_PLACES
from tyche.core.events import (
    BarEvent,
    DistributionEvent,
    Envelope,
    EventBus,
    FillEvent,
    OrderEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.ports import Calendar
from tyche.core.sim.settlement import settlement_date

SUBSCRIBER = "sim-broker"
DEFAULT_MAX_VOLUME_PARTICIPATION = Decimal("0.01")
"""At most 1% of a bar's volume. An assumption; it never binds at a small account's size."""


class SimBrokerError(Exception):
    """The inputs broke an assumption the simulator relies on. A bug, not a market event."""


@dataclass(frozen=True, slots=True)
class FreeRidingViolation:
    """Shares sold before their purchase settled (ADR-0020).

    Attributes:
        client_order_id: The sale that caused it.
        instrument: What was sold.
        trade_date: The day of the sale.
        quantity: Shares sold that had not settled yet.
        purchase_settles_on: When the latest of those purchases would have settled.
    """

    client_order_id: str
    instrument: Instrument
    trade_date: date
    quantity: Decimal
    purchase_settles_on: date


@dataclass(slots=True)
class _Lot:
    """Shares from one purchase, and when that purchase settles."""

    quantity: Decimal
    settles_on: date


@dataclass(slots=True)
class _Working:
    """An accepted order and where it is."""

    state: OrderState
    working: bool = False


class SimBroker:
    """The simulated broker. Implements the ``Broker`` port.

    Subscribe it before anything is published, like every other component.

    Args:
        bus: The run's event bus.
        account: The account at the start, usually ``Account.empty().deposit(...)``.
        costs: Commission, fees, slippage and settlement (``config/costs/<PROFILE>.toml``).
        calendars: A calendar for every calendar code the traded instruments use.
        max_volume_participation: The largest fraction of a bar's volume that can be
            filled, across all orders for that instrument.
    """

    def __init__(
        self,
        bus: EventBus,
        account: Account,
        costs: TradingCosts,
        calendars: Mapping[str, Calendar],
        *,
        max_volume_participation: Decimal = DEFAULT_MAX_VOLUME_PARTICIPATION,
    ) -> None:
        if not max_volume_participation.is_finite() or not 0 < max_volume_participation <= 1:
            raise ValueError(
                f"max_volume_participation must be above 0 and at most 1, "
                f"got {max_volume_participation}"
            )
        self._bus = bus
        self._account = account
        self._costs = costs
        self._calendars = dict(calendars)
        self._participation = max_volume_participation

        self._orders: dict[str, _Working] = {}
        self._sessions: dict[str, Session] = {}
        self._volume_used: dict[Instrument, Decimal] = {}
        # Shares held at the start count as settled long ago.
        self._lots: dict[Instrument, list[_Lot]] = {
            p.instrument: [_Lot(p.quantity, date.min)] for p in account.positions
        }
        self._fills = 0
        self._free_riding: list[FreeRidingViolation] = []
        self._duplicates: list[str] = []

        bus.subscribe(OrderEvent, self._on_order, name=SUBSCRIBER)
        bus.subscribe(SessionEvent, self._on_session, name=SUBSCRIBER)
        bus.subscribe(DistributionEvent, self._on_distribution, name=SUBSCRIBER)
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)

    # --- the Broker port ------------------------------------------------------------

    def account(self) -> Account:
        return self._account

    # --- what a report needs ----------------------------------------------------------

    @property
    def free_riding(self) -> tuple[FreeRidingViolation, ...]:
        """Every free-riding violation so far, in order. Should be empty."""
        return tuple(self._free_riding)

    @property
    def ignored_duplicates(self) -> tuple[str, ...]:
        """Client order ids submitted more than once; the repeats were ignored."""
        return tuple(self._duplicates)

    def order(self, client_order_id: str) -> OrderState | None:
        """The latest state of an order the broker has seen."""
        known = self._orders.get(client_order_id)
        return known.state if known else None

    # --- handlers ---------------------------------------------------------------------

    def _on_order(self, envelope: Envelope[OrderEvent]) -> None:
        state = envelope.event.state
        if state.status is not OrderStatus.SUBMITTED:
            return  # every later status is the broker's own
        order_id = state.order.client_order_id
        if order_id in self._orders:
            self._duplicates.append(order_id)
            return

        reason = self._rejection(state)
        if reason:
            rejected = state.reject(reason)
            self._orders[order_id] = _Working(rejected)
            self._bus.publish(OrderEvent(rejected))
            return
        accepted = state.accept()
        self._orders[order_id] = _Working(accepted)
        self._bus.publish(OrderEvent(accepted))

    def _on_session(self, envelope: Envelope[SessionEvent]) -> None:
        session = envelope.event.session
        if envelope.event.phase is SessionPhase.OPEN:
            self._sessions[session.calendar] = session
            self._account = self._account.settle(session.day)
            for instrument in [i for i in self._volume_used if i.calendar == session.calendar]:
                del self._volume_used[instrument]
            for working in self._open_orders(session.calendar):
                working.working = True
            return

        self._sessions.pop(session.calendar, None)
        for working in self._open_orders(session.calendar):
            order = working.state.order
            if working.working and order.time_in_force is TimeInForce.DAY:
                self._update(working, working.state.expire())

    def _on_distribution(self, envelope: Envelope[DistributionEvent]) -> None:
        distribution = envelope.event.distribution
        held = self._account.position(distribution.instrument)
        if held is None:
            return
        amount = (distribution.amount_per_share * held.quantity).round_to(CENT_PLACES)
        if not amount.is_positive:
            return
        payment_id = (
            f"{distribution.instrument}:{distribution.ex_date.isoformat()}:{distribution.kind}"
        )
        self._account = self._account.receive_distribution(payment_id, amount)

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        bar = envelope.event.bar
        instrument = bar.instrument
        session = self._sessions.get(instrument.calendar)
        if session is None or bar.timestamp != session.closes_at:
            raise SimBrokerError(
                f"bar for {instrument} at {bar.timestamp.isoformat()} does not belong to an "
                f"open {instrument.calendar} session"
            )

        for working in self._open_orders(instrument.calendar):
            if working.working and working.state.order.instrument == instrument:
                self._try_fill(working, bar, session)

        if self._account.position(instrument) is not None:
            self._account = self._account.mark(instrument, _price(bar.close, instrument))

    # --- submission checks -------------------------------------------------------------

    def _rejection(self, state: OrderState) -> str:
        order = state.order
        if order.instrument.currency is not self._costs.currency:
            return (
                f"{order.instrument} trades in {order.instrument.currency}, but this broker's "
                f"costs are in {self._costs.currency}"
            )
        if order.instrument.calendar not in self._calendars:
            return f"no calendar loaded for {order.instrument.calendar}"
        if order.quantity != order.quantity.to_integral_value():
            return f"whole shares only: cannot trade {order.quantity} (ADR-0020)"
        if order.order_type is OrderType.STOP and order.side is Side.BUY:
            return "buy stops are not supported: Tyche is long-only"
        if order.side is Side.SELL:
            held = self._held(order.instrument)
            if order.quantity > held:
                return f"cannot sell {order.quantity} {order.instrument}: {held} held"
        return ""

    # --- filling -----------------------------------------------------------------------

    def _try_fill(self, working: _Working, bar: Bar, session: Session) -> None:
        order = working.state.order
        reference, at = self._trigger(working, bar, session)
        if reference is None:
            return

        quantity = min(working.state.remaining, self._volume_left(bar))
        if quantity <= 0:
            return  # no volume left in this bar; a day order expires at the close

        price = self._costs.fill_price(order.side, reference)
        cost = self._costs.cost_of(order.side, quantity, price).total

        if order.side is Side.BUY:
            settled = self._account.cash(order.instrument.currency).settled
            needed = price * quantity + cost
            if needed > settled:
                note = (
                    "insufficient settled cash at the open: "
                    f"needs {needed.round_to(CENT_PLACES)}, has {settled}"
                )
                self._update(working, working.state.cancel(note))
                return
        else:
            held = self._held(order.instrument)
            if quantity > held:
                note = f"cannot sell {quantity} {order.instrument}: only {held} held"
                self._update(working, working.state.cancel(note))
                return

        self._fills += 1
        fill = Fill(
            fill_id=f"sim-{self._fills:06d}",
            client_order_id=order.client_order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=quantity,
            price=price,
            commission=cost,
            filled_at=at,
            trade_date=session.day,
            settles_on=settlement_date(
                session.day,
                self._costs.settlement_days,
                self._calendars[order.instrument.calendar],
            ),
        )
        self._account = self._account.apply_fill(fill)
        used = self._volume_used.get(order.instrument, Decimal(0))
        self._volume_used[order.instrument] = used + quantity
        self._track_lots(fill)
        self._bus.publish(FillEvent(fill))
        self._update(working, working.state.fill(quantity))

    def _trigger(
        self, working: _Working, bar: Bar, session: Session
    ) -> tuple[Money | None, datetime]:
        """The reference price and time of a fill on this bar; ``None`` if it does not trigger."""
        order = working.state.order
        opening = _price(bar.open, order.instrument)
        if order.order_type is OrderType.MARKET:
            return opening, session.opens_at
        stop = order.stop_price
        if stop is None:  # pragma: no cover - Order guarantees a stop order has a price
            raise SimBrokerError(f"stop order {order.client_order_id} has no stop price")
        if opening <= stop:
            return opening, session.opens_at
        if _price(bar.low, order.instrument) <= stop:
            return stop, session.closes_at
        return None, session.closes_at

    def _volume_left(self, bar: Bar) -> Decimal:
        allowed = (Decimal(repr(bar.volume)) * self._participation).quantize(
            Decimal(1), ROUND_FLOOR
        )
        return allowed - self._volume_used.get(bar.instrument, Decimal(0))

    def _track_lots(self, fill: Fill) -> None:
        lots = self._lots.setdefault(fill.instrument, [])
        if fill.side is Side.BUY:
            lots.append(_Lot(fill.quantity, fill.settles_on))
            return

        to_match = fill.quantity
        unsettled = Decimal(0)
        latest: date | None = None
        while to_match > 0:
            lot = lots[0]
            used = min(lot.quantity, to_match)
            if lot.settles_on > fill.trade_date:
                unsettled += used
                latest = lot.settles_on if latest is None else max(latest, lot.settles_on)
            lot.quantity -= used
            to_match -= used
            if lot.quantity == 0:
                lots.pop(0)
        if latest is not None:
            self._free_riding.append(
                FreeRidingViolation(
                    fill.client_order_id, fill.instrument, fill.trade_date, unsettled, latest
                )
            )

    # --- helpers -----------------------------------------------------------------------

    def _held(self, instrument: Instrument) -> Decimal:
        position = self._account.position(instrument)
        return position.quantity if position else Decimal(0)

    def _open_orders(self, calendar: str) -> list[_Working]:
        return [
            w
            for w in self._orders.values()
            if not w.state.status.is_terminal and w.state.order.instrument.calendar == calendar
        ]

    def _update(self, working: _Working, state: OrderState) -> None:
        working.state = state
        self._bus.publish(OrderEvent(state))


def _price(value: float, instrument: Instrument) -> Money:
    """A bar price as exact money. ``repr`` gives the shortest decimal that round-trips."""
    return Money(Decimal(repr(value)), instrument.currency)

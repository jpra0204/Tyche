"""Orders and their lifecycle.

An ``Order`` is what Tyche decided to ask the broker for; it never changes. What the
broker did with it is an ``OrderState``: a status, and the fills received so far. Every
change of status goes through one table of allowed transitions, so an order can never
be, say, filled after it was cancelled.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.validation import require_utc


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    STOP = "stop"
    """Becomes a market order once the price trades through ``stop_price`` (ADR-0006)."""


class TimeInForce(StrEnum):
    DAY = "day"
    """Expires at the end of the session if not filled."""

    GTC = "gtc"
    """Good till cancelled. Protective stops rest this way (ADR-0006)."""


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)

_ALLOWED: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED}),
    OrderStatus.SUBMITTED: frozenset({OrderStatus.ACCEPTED, OrderStatus.REJECTED}),
    OrderStatus.ACCEPTED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


class OrderError(ValueError):
    """An order or a change to it breaks the lifecycle rules."""


@dataclass(frozen=True, slots=True)
class Order:
    """A request to buy or sell, as Tyche decided it. Never changes once created.

    Attributes:
        client_order_id: Tyche's own identifier, derived from the decision that made
            the order. Sending the same decision twice gives the same id, so the broker
            adapter can drop the duplicate (brief, section 4.2).
        instrument: What to trade.
        side: Buy or sell.
        quantity: How many shares. The type allows fractions, but Tyche sizes
            orders in whole shares because IBKR's API cannot place fractional
            orders (ADR-0020).
        order_type: Market or stop.
        time_in_force: Day or good-till-cancelled.
        created_at: When Tyche decided it, in UTC.
        reason: Why, in words, for the journal.
        stop_price: The trigger price, for a stop order only.
    """

    client_order_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    created_at: datetime
    reason: str
    stop_price: Money | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise OrderError("an order needs a client_order_id")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise OrderError(f"order {self.client_order_id}: quantity must be positive")
        require_utc(self.created_at, f"order {self.client_order_id}: created_at")
        if self.order_type is OrderType.STOP:
            if self.stop_price is None:
                raise OrderError(f"order {self.client_order_id}: a stop order needs a stop price")
            if not self.stop_price.is_positive:
                raise OrderError(f"order {self.client_order_id}: stop price must be positive")
            if self.stop_price.currency is not self.instrument.currency:
                raise OrderError(
                    f"order {self.client_order_id}: stop price is in "
                    f"{self.stop_price.currency}, {self.instrument} trades in "
                    f"{self.instrument.currency}"
                )
        elif self.stop_price is not None:
            raise OrderError(f"order {self.client_order_id}: only a stop order has a stop price")


@dataclass(frozen=True, slots=True)
class OrderState:
    """Where an order is in its lifecycle. Every method returns a new state.

    Attributes:
        order: The order.
        status: Its current status.
        filled_quantity: Shares filled so far.
        note: Why the last status change happened, such as a rejection reason.
    """

    order: Order
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: Decimal = Decimal(0)
    note: str = ""

    @property
    def remaining(self) -> Decimal:
        return self.order.quantity - self.filled_quantity

    def submit(self) -> OrderState:
        return self._move(OrderStatus.SUBMITTED)

    def accept(self) -> OrderState:
        return self._move(OrderStatus.ACCEPTED)

    def reject(self, reason: str) -> OrderState:
        return self._move(OrderStatus.REJECTED, reason)

    def cancel(self, reason: str = "") -> OrderState:
        return self._move(OrderStatus.CANCELLED, reason)

    def expire(self) -> OrderState:
        return self._move(OrderStatus.EXPIRED)

    def fill(self, quantity: Decimal) -> OrderState:
        """Record ``quantity`` more shares filled."""
        label = f"order {self.order.client_order_id}"
        if not quantity.is_finite() or quantity <= 0:
            raise OrderError(f"{label}: fill quantity must be positive")
        if quantity > self.remaining:
            raise OrderError(f"{label}: fill of {quantity} exceeds the {self.remaining} remaining")
        filled = self.filled_quantity + quantity
        target = (
            OrderStatus.FILLED if filled == self.order.quantity else OrderStatus.PARTIALLY_FILLED
        )
        return replace(self._move(target), filled_quantity=filled)

    def _move(self, target: OrderStatus, note: str = "") -> OrderState:
        if target not in _ALLOWED[self.status]:
            raise OrderError(
                f"order {self.order.client_order_id}: cannot go from {self.status} to {target}"
            )
        return replace(self, status=target, note=note)

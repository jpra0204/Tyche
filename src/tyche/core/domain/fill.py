"""Fill: shares that actually changed hands."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.order import Side
from tyche.core.domain.validation import require_utc


@dataclass(frozen=True, slots=True)
class Fill:
    """An execution reported by the broker. One order may have several.

    Attributes:
        fill_id: The broker's identifier for this execution. Applying the same fill
            twice is refused, so a resent report cannot count twice.
        client_order_id: The order it belongs to.
        instrument: What was traded.
        side: Buy or sell.
        quantity: Shares that changed hands.
        price: Price per share, in the instrument's currency.
        commission: Commission charged, in the same currency. A different currency is
            refused for now; PR 9 checks how IBKR actually charges.
        filled_at: When it happened, in UTC.
        trade_date: The exchange's own date for the trade.
        settles_on: The date the cash and shares settle. The broker's settlement rule
            decides it (PR 9); the ledger only records it.
    """

    fill_id: str
    client_order_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    price: Money
    commission: Money
    filled_at: datetime
    trade_date: date
    settles_on: date

    def __post_init__(self) -> None:
        label = f"fill {self.fill_id}"
        if not self.fill_id.strip() or not self.client_order_id.strip():
            raise ValueError("a fill needs a fill_id and a client_order_id")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError(f"{label}: quantity must be positive")
        if not self.price.is_positive:
            raise ValueError(f"{label}: price must be positive")
        if self.price.currency is not self.instrument.currency:
            raise ValueError(
                f"{label}: price is in {self.price.currency}, "
                f"{self.instrument} trades in {self.instrument.currency}"
            )
        if self.commission.is_negative:
            raise ValueError(f"{label}: commission cannot be negative")
        if self.commission.currency is not self.price.currency:
            raise ValueError(f"{label}: commission must be in the trade currency for now")
        require_utc(self.filled_at, f"{label}: filled_at")
        if self.settles_on < self.trade_date:
            raise ValueError(f"{label}: settles before it trades")

    @property
    def gross(self) -> Money:
        """Price times quantity, before commission."""
        return self.price * self.quantity

    @property
    def cash_flow(self) -> Money:
        """Cash in (positive) or out (negative) of the account, commission included."""
        if self.side is Side.BUY:
            return -(self.gross + self.commission)
        return self.gross - self.commission

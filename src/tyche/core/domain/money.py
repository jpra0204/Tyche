"""Money: an exact amount in one currency.

See ADR-0012 for why money is ``Decimal`` and never ``float``.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import overload

from tyche.core.domain.currency import Currency


class CurrencyMismatchError(ValueError):
    """Raised when two amounts in different currencies are added or compared."""

    def __init__(self, left: Currency, right: Currency) -> None:
        super().__init__(
            f"cannot combine {left} with {right}: convert explicitly with an exchange rate first"
        )
        self.left = left
        self.right = right


def _as_scalar(value: object) -> Decimal | None:
    """Return ``value`` as a Decimal if it is an exact number, otherwise ``None``.

    ``float`` is deliberately not accepted: it is the type this class exists to keep
    out of the ledger. ``bool`` is an ``int`` in Python and is rejected as well.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    return None


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount of one currency.

    Immutable. Arithmetic returns a new ``Money``. Adding, subtracting or comparing two
    different currencies raises ``CurrencyMismatchError``; there is no implicit
    conversion anywhere in Tyche.

    The amount is not rounded. Rounding to cents happens where a rule for it exists
    (commissions, fills), not silently inside arithmetic.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        # Typed as ``object`` because the whole point is to catch a caller that got
        # past the type checker, for example a float taken from a pandas frame.
        amount: object = self.amount
        if not isinstance(amount, Decimal):
            raise TypeError(
                f"Money amount must be a Decimal, got {type(amount).__name__}; "
                "use Money.of() to build one from a string or an int"
            )
        if not amount.is_finite():
            raise ValueError(f"Money amount must be finite, got {amount}")

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: Currency) -> Money:
        """Build Money from an exact value: a Decimal, an int or a decimal string."""
        raw: object = amount
        if isinstance(raw, (float, bool)):
            raise TypeError(
                f"Money.of() does not accept {type(raw).__name__}; pass a string such as '12.34'"
            )
        try:
            return cls(Decimal(amount), currency)
        except InvalidOperation:
            raise ValueError(f"not a valid decimal amount: {amount!r}") from None

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        """Zero in the given currency. Useful as the start value of a sum."""
        return cls(Decimal(0), currency)

    # --- inspection -----------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def round_to(self, places: int) -> Money:
        """Round to ``places`` decimal places, halves to even (banker's rounding).

        Rounding never happens implicitly. Code that needs it calls this, at the one
        point where a rule says how: the ledger's cost allocation, a broker's
        commission to the cent.
        """
        if places < 0:
            raise ValueError("places must be zero or more")
        return Money(
            self.amount.quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN), self.currency
        )

    # --- arithmetic with Money of the same currency -----------------------------

    def _require_same_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    # --- arithmetic with plain numbers -------------------------------------------

    def __mul__(self, factor: Decimal | int) -> Money:
        scalar = _as_scalar(factor)
        if scalar is None:
            return NotImplemented
        return Money(self.amount * scalar, self.currency)

    def __rmul__(self, factor: Decimal | int) -> Money:
        return self.__mul__(factor)

    @overload
    def __truediv__(self, divisor: Money) -> Decimal: ...
    @overload
    def __truediv__(self, divisor: Decimal | int) -> Money: ...
    def __truediv__(self, divisor: Money | Decimal | int) -> Money | Decimal:
        """Divide by a number to get Money, or by Money to get a plain ratio.

        ``position_value / equity`` is a weight, which has no currency.
        """
        if isinstance(divisor, Money):
            self._require_same_currency(divisor)
            return self.amount / divisor.amount
        scalar = _as_scalar(divisor)
        if scalar is None:
            return NotImplemented
        return Money(self.amount / scalar, self.currency)

    # --- ordering ----------------------------------------------------------------
    # Written by hand: dataclass(order=True) would happily order USD against CAD.

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount >= other.amount

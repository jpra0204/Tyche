"""Corporate actions: cash distributions and stock splits.

Tyche keeps prices adjusted for splits only, and treats dividends as cash paid to
whoever holds the shares on the ex-date (ADR-0019). That is how a real account sees
them, and it is what the tax export needs.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money


class DistributionKind(StrEnum):
    """Why cash was paid out. Taxed differently, so kept apart."""

    DIVIDEND = "dividend"
    CAPITAL_GAIN = "capital_gain"
    """A fund passing on gains it realised. Common for ETFs at year end."""


@dataclass(frozen=True, slots=True)
class CashDistribution:
    """Cash paid per share to holders of ``instrument`` on its ex-date.

    Attributes:
        instrument: Who pays.
        ex_date: The first session on which a buyer no longer receives the payment.
            Holders at the previous session's close are paid.
        amount_per_share: Cash per share, in the instrument's currency, before any tax
            withheld.
        kind: Dividend or capital-gain distribution.
    """

    instrument: Instrument
    ex_date: date
    amount_per_share: Money
    kind: DistributionKind

    def __post_init__(self) -> None:
        if not self.amount_per_share.is_positive:
            raise ValueError(f"{self}: amount per share must be positive")
        if self.amount_per_share.currency is not self.instrument.currency:
            raise ValueError(
                f"{self}: paid in {self.amount_per_share.currency}, but {self.instrument} "
                f"trades in {self.instrument.currency}"
            )

    def __str__(self) -> str:
        return f"{self.instrument} {self.kind} {self.amount_per_share} ex {self.ex_date}"


@dataclass(frozen=True, slots=True)
class Split:
    """A change in the number of shares, effective from ``ex_date``.

    Attributes:
        instrument: Whose shares split.
        ex_date: First session at the new share count.
        ratio: New shares per old share: ``10`` for a 10-for-1 split, ``0.1`` for a
            1-for-10 reverse split.
    """

    instrument: Instrument
    ex_date: date
    ratio: Decimal

    def __post_init__(self) -> None:
        ratio: object = self.ratio
        if not isinstance(ratio, Decimal):
            raise TypeError(f"split ratio must be a Decimal, got {type(ratio).__name__}")
        if not self.ratio.is_finite() or self.ratio <= 0 or self.ratio == 1:
            raise ValueError(f"{self}: ratio must be positive and not 1")

    def __str__(self) -> str:
        return f"{self.instrument} split {self.ratio}-for-1 ex {self.ex_date}"

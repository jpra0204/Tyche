"""The universe and screening types: which instruments may be traded, and how they rank.

``UniverseRules`` is what a market profile says an eligible instrument looks like. The
universe stage applies the rules at every decision cycle and reports each instrument
as either a ``UniverseMember`` (with the measurements that let it in) or an
``Exclusion`` (with the reason). Screening ranks the members into ``ScoredInstrument``.
"""

from dataclasses import dataclass
from enum import StrEnum

from tyche.core.domain.bar_history import DataIssueKind
from tyche.core.domain.currency import Currency
from tyche.core.domain.instrument import AssetClass, Instrument
from tyche.core.domain.money import Money

DISQUALIFYING_ISSUES = frozenset(
    {
        DataIssueKind.MISSING_SESSION,
        DataIssueKind.CONFLICT,
        DataIssueKind.INVALID_BAR,
        DataIssueKind.SUSPECT_MOVE,
    }
)
"""Data issues that keep an instrument out of the universe for a while (ADR-0018).

Each one means a recent price may be wrong or absent. ``DUPLICATE`` is not here: the
copies were identical, so the bar kept is right. Issues without a session day
(``OFF_SESSION``, ``WRONG_SERIES``, ``MIXED_ADJUSTMENT``) are not here either: they
describe bars dropped before caching, and any session left without a bar is reported
again as ``MISSING_SESSION``.
"""


@dataclass(frozen=True, slots=True)
class UniverseRules:
    """What an instrument must look like to be eligible under a market profile.

    The thresholds are choices, not market facts. They exist to keep out instruments
    whose prices cannot be trusted or traded at a fair price: very cheap shares, thin
    trading and broken data.

    Attributes:
        asset_classes: The kinds of instrument allowed, e.g. stocks and ETFs.
        min_price: The lowest last close allowed, in the profile's currency. Compared
            with split-adjusted prices (ADR-0019), so before a split the price seen
            is lower than the price that traded, and an instrument can be excluded
            that was above the minimum at the time.
        min_average_dollar_volume: The lowest average of close times volume over the
            last ``liquidity_sessions`` bars. Split adjustment does not change this
            product, so it is the value that really traded.
        liquidity_sessions: How many bars the average needs. An instrument with fewer
            bars so far is excluded for lack of history.
        quality_sessions: How many decision cycles an instrument stays excluded after
            a disqualifying data issue about it is reported, counting the cycle of the
            report.
        instruments: The candidates: every instrument followed under the profile. A
            backtest replays these, and paper and live will fetch them; the rules above
            decide at each cycle which of them are eligible. Each must be quoted in the
            thresholds' currency and be of an allowed asset class.
    """

    asset_classes: tuple[AssetClass, ...]
    min_price: Money
    min_average_dollar_volume: Money
    liquidity_sessions: int
    quality_sessions: int
    instruments: tuple[Instrument, ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_classes:
            raise ValueError("universe rules: need at least one asset class")
        if len(set(self.asset_classes)) != len(self.asset_classes):
            raise ValueError("universe rules: asset classes are repeated")
        if self.min_price.currency is not self.min_average_dollar_volume.currency:
            raise ValueError(
                "universe rules: min_price and min_average_dollar_volume must be in one "
                f"currency, got {self.min_price.currency} and "
                f"{self.min_average_dollar_volume.currency}"
            )
        if self.min_price.amount <= 0:
            raise ValueError(f"universe rules: min_price must be positive, got {self.min_price}")
        if self.min_average_dollar_volume.amount < 0:
            raise ValueError("universe rules: min_average_dollar_volume cannot be negative")
        if self.liquidity_sessions < 1:
            raise ValueError("universe rules: liquidity_sessions must be at least 1")
        if self.quality_sessions < 1:
            raise ValueError("universe rules: quality_sessions must be at least 1")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("universe rules: instruments are repeated")
        for instrument in self.instruments:
            if instrument.currency is not self.currency:
                raise ValueError(
                    f"universe rules: {instrument} is quoted in {instrument.currency}, but "
                    f"the thresholds are in {self.currency}"
                )
            if instrument.asset_class not in self.asset_classes:
                raise ValueError(
                    f"universe rules: {instrument} is of asset class "
                    f"{instrument.asset_class}, which is not allowed"
                )

    @property
    def currency(self) -> Currency:
        """The currency the thresholds are in. Only instruments quoted in it are eligible."""
        return self.min_price.currency


class ExclusionReason(StrEnum):
    """Why an instrument is not eligible. The universe checks them in this order."""

    NOT_IN_PROFILE = "not_in_profile"
    """Its calendar, currency or asset class is not one the profile trades."""

    NO_BAR = "no_bar"
    """There is no bar for this decision time, so there is no current price."""

    DATA_ISSUE = "data_issue"
    """A disqualifying data issue was reported recently."""

    INSUFFICIENT_HISTORY = "insufficient_history"
    """Fewer bars so far than the liquidity average needs."""

    PRICE_TOO_LOW = "price_too_low"
    """The last close is below the minimum price."""

    ILLIQUID = "illiquid"
    """The average dollar volume is below the minimum."""


@dataclass(frozen=True, slots=True)
class Exclusion:
    """An instrument left out of the universe, and why.

    Attributes:
        instrument: What was left out.
        reason: The first rule it failed.
        detail: A sentence a person can check, with the numbers involved.
    """

    instrument: Instrument
    reason: ExclusionReason
    detail: str

    def __str__(self) -> str:
        return f"{self.instrument} {self.reason}: {self.detail}"


@dataclass(frozen=True, slots=True)
class UniverseMember:
    """An eligible instrument, with the measurements that let it in.

    The measurements are estimates from market data, so they are ``float`` like the
    bar prices they come from (ADR-0012). Both are in the instrument's currency.

    Attributes:
        instrument: The eligible instrument.
        last_close: Its close at this decision time, split-adjusted.
        average_dollar_volume: The mean of close times volume over the last
            ``liquidity_sessions`` bars.
    """

    instrument: Instrument
    last_close: float
    average_dollar_volume: float


@dataclass(frozen=True, slots=True)
class ScoredInstrument:
    """One entry of a screen's ranking. Higher scores rank first.

    Attributes:
        instrument: The instrument ranked.
        score: What the screen measured. Its meaning depends on the screen.
    """

    instrument: Instrument
    score: float

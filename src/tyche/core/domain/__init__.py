"""Value objects shared by the whole system.

Immutable data with no behaviour that needs I/O. Every object validates itself when it
is created, so an instance that exists can be trusted everywhere it travels.

Available now: ``Currency``, ``Money``, ``Timeframe``, ``Instrument``, ``AssetClass``,
``Bar`` with its ``PriceAdjustment``, ``Session``, ``MarketProfile``, the corporate
actions ``CashDistribution`` and ``Split``, and ``BarHistory`` with the data-quality
audit that produces it.

Planned (Phase 1, PR 8): ``Order``, ``Fill``, ``Position`` and ``Account`` (cash per
currency).
"""

from tyche.core.domain.bar import Bar, PriceAdjustment
from tyche.core.domain.bar_history import (
    DEFAULT_MAX_DAILY_MOVE,
    BarHistory,
    DataIssue,
    DataIssueKind,
    audit_daily_bars,
)
from tyche.core.domain.corporate_actions import CashDistribution, DistributionKind, Split
from tyche.core.domain.currency import Currency
from tyche.core.domain.instrument import AssetClass, Instrument
from tyche.core.domain.market_profile import MarketProfile, require_profile_name
from tyche.core.domain.money import CurrencyMismatchError, Money
from tyche.core.domain.session import Session
from tyche.core.domain.timeframe import Timeframe

__all__ = [
    "DEFAULT_MAX_DAILY_MOVE",
    "AssetClass",
    "Bar",
    "BarHistory",
    "CashDistribution",
    "Currency",
    "CurrencyMismatchError",
    "DataIssue",
    "DataIssueKind",
    "DistributionKind",
    "Instrument",
    "MarketProfile",
    "Money",
    "PriceAdjustment",
    "Session",
    "Split",
    "Timeframe",
    "audit_daily_bars",
    "require_profile_name",
]

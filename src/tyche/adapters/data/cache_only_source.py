"""CacheOnlySource: a ``BarSource`` that never fetches, so a backtest never goes online.

Put behind a ``CachedDataProvider``, it lets the provider answer from the cache as
usual and turns every request for sessions the cache has not covered into a
``NotCachedError``. A backtest then runs on exactly the data already fetched, and says
what to fetch when something is missing, instead of quietly downloading new data
(Yahoo revises history) in the middle of a run.
"""

from datetime import date

from tyche.adapters.data.cached_provider import SourceData
from tyche.core.domain import Instrument, PriceAdjustment
from tyche.core.ports import DataError


class NotCachedError(DataError):
    """Sessions of ``instrument`` from ``first`` to ``last`` are not in the cache."""

    def __init__(self, instrument: Instrument, first: date, last: date) -> None:
        super().__init__(f"{instrument}: sessions from {first} to {last} are not in the cache yet")
        self.instrument = instrument
        self.first = first
        self.last = last


class CacheOnlySource:
    """Implements ``BarSource`` by refusing every fetch.

    Args:
        name: The name of the source whose cache is read, e.g. ``yfinance``. It must
            match the cache, which keeps the data of each source apart.
        adjustment: How that source's prices are adjusted.
    """

    def __init__(self, name: str, adjustment: PriceAdjustment) -> None:
        self._name = name
        self._adjustment = adjustment

    @property
    def name(self) -> str:
        return self._name

    @property
    def adjustment(self) -> PriceAdjustment:
        return self._adjustment

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        raise NotCachedError(instrument, first, last)

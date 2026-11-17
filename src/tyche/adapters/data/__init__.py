"""``DataProvider`` adapters.

Available now:

* ``ParquetBarCache``: daily bars on disk, one Parquet file per instrument, with the
  time each bar was fetched and the date ranges already asked of the source.
* ``CachedDataProvider``: implements ``DataProvider`` as a read-through cache over any
  ``BarSource``, auditing every answer against the trading calendar.
* ``BarSource`` and ``SourceData``: what a data vendor adapter implements and returns.

* ``YFinanceSource``: daily bars and corporate actions from Yahoo Finance, with retries.
  Yahoo's data is for personal use only; see the module docstring.
"""

from tyche.adapters.data.cached_provider import BarSource, CachedDataProvider, SourceData
from tyche.adapters.data.parquet_cache import (
    CACHE_FORMAT,
    CachedBar,
    CacheEntry,
    DateRange,
    ParquetBarCache,
)
from tyche.adapters.data.yfinance_source import YFinanceSource, yfinance_fetcher

__all__ = [
    "CACHE_FORMAT",
    "BarSource",
    "CacheEntry",
    "CachedBar",
    "CachedDataProvider",
    "DateRange",
    "ParquetBarCache",
    "SourceData",
    "YFinanceSource",
    "yfinance_fetcher",
]

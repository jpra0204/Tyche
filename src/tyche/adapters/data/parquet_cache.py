"""A local cache of daily bars in Parquet files (ADR-0009).

One file per source, timeframe and instrument::

    <root>/<source>/<timeframe>/<exchange>/<symbol>.parquet

Each row is one bar plus the moment it was fetched. The file's metadata records which
instrument it belongs to, how its prices are adjusted, the dividends and splits seen,
and which date ranges have already been asked of the source ("coverage"), so a gap
the source cannot fill is not fetched again on every run.
"""

import json
import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from tyche.core.domain import (
    AssetClass,
    Bar,
    CashDistribution,
    Currency,
    DistributionKind,
    Instrument,
    Money,
    PriceAdjustment,
    Split,
    Timeframe,
)
from tyche.core.domain.validation import require_utc
from tyche.core.ports import DataError

CACHE_FORMAT = 2
_METADATA_KEY = b"tyche"
_SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
_ONE_DAY = timedelta(days=1)

_FIELDS: list[pa.Field[Any]] = [
    pa.field("timestamp", pa.timestamp("us", tz="UTC")),
    pa.field("open", pa.float64()),
    pa.field("high", pa.float64()),
    pa.field("low", pa.float64()),
    pa.field("close", pa.float64()),
    pa.field("volume", pa.float64()),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
]
_SCHEMA = pa.schema(_FIELDS)


@dataclass(frozen=True, slots=True)
class DateRange:
    """An inclusive range of session days."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.first > self.last:
            raise ValueError(f"empty date range: {self.first} is after {self.last}")

    def contains(self, day: date) -> bool:
        return self.first <= day <= self.last


@dataclass(frozen=True, slots=True)
class CachedBar:
    """A bar and the moment it was fetched from its source, in UTC."""

    bar: Bar
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Everything cached for one instrument and timeframe. Immutable; ``merged`` returns a new one.

    Attributes:
        instrument: Whose bars these are.
        timeframe: The bars' timeframe.
        adjustment: How prices are adjusted, or ``None`` while the entry is empty.
        rows: Cached bars, oldest first, one per timestamp.
        coverage: Session-day ranges already asked of the source, sorted and disjoint.
        distributions: Cash distributions seen, oldest first, one per date and kind.
        splits: Splits seen, oldest first, one per date.
    """

    instrument: Instrument
    timeframe: Timeframe
    adjustment: PriceAdjustment | None = None
    rows: tuple[CachedBar, ...] = ()
    coverage: tuple[DateRange, ...] = field(default=())
    distributions: tuple[CashDistribution, ...] = ()
    splits: tuple[Split, ...] = ()

    def covers(self, day: date) -> bool:
        """True if the source has already been asked about ``day``."""
        return any(span.contains(day) for span in self.coverage)

    def bars_between(self, start: datetime, end: datetime) -> tuple[CachedBar, ...]:
        """Cached bars stamped from ``start`` to ``end`` inclusive."""
        return tuple(row for row in self.rows if start <= row.bar.timestamp <= end)

    def distributions_between(self, first: date, last: date) -> tuple[CashDistribution, ...]:
        """Distributions with an ex-date from ``first`` to ``last`` inclusive."""
        return tuple(d for d in self.distributions if first <= d.ex_date <= last)

    def splits_between(self, first: date, last: date) -> tuple[Split, ...]:
        """Splits with an ex-date from ``first`` to ``last`` inclusive."""
        return tuple(s for s in self.splits if first <= s.ex_date <= last)

    def merged(
        self,
        bars: Sequence[Bar],
        *,
        fetched_at: datetime,
        covered: DateRange | None,
        adjustment: PriceAdjustment,
        distributions: Sequence[CashDistribution] = (),
        splits: Sequence[Split] = (),
    ) -> CacheEntry:
        """Return a new entry with ``bars`` and corporate actions added.

        A new bar replaces a cached bar with the same timestamp: sources revise
        history, and the newer fetch is taken as the better one. Its ``fetched_at``
        records that it changed. Distributions and splits are replaced the same way,
        by date (and kind, for distributions).
        """
        require_utc(fetched_at, "fetched_at")
        if self.adjustment is not None and self.adjustment is not adjustment:
            raise DataError(
                f"cache for {self.instrument} holds prices adjusted for "
                f"'{self.adjustment}'; refusing to mix in prices adjusted for '{adjustment}'"
            )
        actions: list[CashDistribution | Split] = [*distributions, *splits]
        for action in actions:
            if action.instrument != self.instrument:
                raise DataError(f"cannot cache {action} in the cache for {self.instrument}")
        for bar in bars:
            if bar.instrument != self.instrument or bar.timeframe is not self.timeframe:
                raise DataError(
                    f"cannot cache a bar of {bar.instrument} in the cache for {self.instrument}"
                )
            if bar.adjustment is not adjustment:
                raise DataError(
                    f"cannot cache a bar at {bar.timestamp.isoformat()} with the wrong adjustment"
                )

        by_time = {row.bar.timestamp: row for row in self.rows}
        for bar in bars:
            by_time[bar.timestamp] = CachedBar(bar, fetched_at)
        rows = tuple(by_time[stamp] for stamp in sorted(by_time))
        coverage = self.coverage if covered is None else _add_range(self.coverage, covered)

        by_distribution = {(d.ex_date, d.kind): d for d in self.distributions}
        by_distribution.update({(d.ex_date, d.kind): d for d in distributions})
        by_split = {s.ex_date: s for s in self.splits}
        by_split.update({s.ex_date: s for s in splits})

        return replace(
            self,
            adjustment=adjustment,
            rows=rows,
            coverage=coverage,
            distributions=tuple(by_distribution[key] for key in sorted(by_distribution)),
            splits=tuple(by_split[day] for day in sorted(by_split)),
        )


class ParquetBarCache:
    """Reads and writes ``CacheEntry`` objects as Parquet files under ``root``.

    Writes are atomic: a new file is written beside the old one and renamed over it,
    so a crash mid-write leaves the previous file intact.
    """

    def __init__(self, root: Path, *, source: str) -> None:
        if not _SOURCE_NAME.fullmatch(source):
            raise ValueError(
                f"invalid source name {source!r}: use lower-case letters, digits, '-' or '_'"
            )
        self._root = root
        self._source = source

    @property
    def source(self) -> str:
        return self._source

    def path_for(self, instrument: Instrument, timeframe: Timeframe) -> Path:
        return (
            self._root
            / self._source
            / timeframe.value
            / instrument.exchange
            / f"{instrument.symbol}.parquet"
        )

    def load(self, instrument: Instrument, timeframe: Timeframe) -> CacheEntry:
        """Return what is cached, or an empty entry if nothing is."""
        path = self.path_for(instrument, timeframe)
        if not path.exists():
            return CacheEntry(instrument, timeframe)
        try:
            table = pq.read_table(path)
        except (OSError, pa.ArrowException) as error:
            raise DataError(f"cannot read cache file {path}: {error}") from None
        if not table.schema.equals(_SCHEMA, check_metadata=False):
            raise DataError(f"cache file {path} has an unexpected layout")

        metadata = _read_metadata(path, table.schema.metadata)
        stored = _instrument_from(metadata["instrument"])
        if stored != instrument or metadata["timeframe"] != timeframe.value:
            raise DataError(
                f"cache file {path} belongs to {stored} {metadata['timeframe']}, "
                f"not {instrument} {timeframe}"
            )
        try:
            adjustment = PriceAdjustment(metadata["adjustment"])
            distributions = tuple(
                _distribution_from(instrument, d) for d in metadata["distributions"]
            )
            splits = tuple(_split_from(instrument, s) for s in metadata["splits"])
        except (KeyError, ValueError, InvalidOperation) as error:
            raise DataError(f"cache file {path} has invalid metadata: {error!r}") from None

        try:
            rows = tuple(
                CachedBar(
                    Bar(
                        instrument=instrument,
                        timeframe=timeframe,
                        timestamp=record["timestamp"],
                        open=record["open"],
                        high=record["high"],
                        low=record["low"],
                        close=record["close"],
                        volume=record["volume"],
                        adjustment=adjustment,
                    ),
                    record["fetched_at"],
                )
                for record in table.to_pylist()
            )
        except ValueError as error:
            raise DataError(f"cache file {path} holds an invalid bar: {error}") from None

        coverage = tuple(
            DateRange(date.fromisoformat(a), date.fromisoformat(b)) for a, b in metadata["coverage"]
        )
        return CacheEntry(instrument, timeframe, adjustment, rows, coverage, distributions, splits)

    def store(self, entry: CacheEntry) -> None:
        """Write ``entry``, replacing any previous file for the same instrument."""
        if entry.adjustment is None:
            raise DataError(f"refusing to store an empty cache entry for {entry.instrument}")
        path = self.path_for(entry.instrument, entry.timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        metadata = {
            "format": CACHE_FORMAT,
            "instrument": _instrument_to(entry.instrument),
            "timeframe": entry.timeframe.value,
            "adjustment": entry.adjustment.value,
            "coverage": [
                [span.first.isoformat(), span.last.isoformat()] for span in entry.coverage
            ],
            # Amounts and ratios are written as text so that Decimal values stay exact.
            "distributions": [
                {
                    "ex_date": d.ex_date.isoformat(),
                    "amount": str(d.amount_per_share.amount),
                    "currency": d.amount_per_share.currency.value,
                    "kind": d.kind.value,
                }
                for d in entry.distributions
            ],
            "splits": [
                {"ex_date": s.ex_date.isoformat(), "ratio": str(s.ratio)} for s in entry.splits
            ],
        }
        columns: dict[str, list[Any]] = {
            "timestamp": [row.bar.timestamp for row in entry.rows],
            "open": [row.bar.open for row in entry.rows],
            "high": [row.bar.high for row in entry.rows],
            "low": [row.bar.low for row in entry.rows],
            "close": [row.bar.close for row in entry.rows],
            "volume": [row.bar.volume for row in entry.rows],
            "fetched_at": [row.fetched_at for row in entry.rows],
        }
        schema = _SCHEMA.with_metadata(
            {_METADATA_KEY: json.dumps(metadata, sort_keys=True).encode()}
        )
        table = pa.Table.from_pydict(columns, schema=schema)

        handle, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        os.close(handle)
        try:
            pq.write_table(table, temporary)
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _add_range(ranges: Iterable[DateRange], new: DateRange) -> tuple[DateRange, ...]:
    """Insert ``new`` and merge ranges that overlap or touch."""
    merged: list[DateRange] = []
    for span in sorted([*ranges, new], key=lambda r: r.first):
        if merged and span.first <= merged[-1].last + _ONE_DAY:
            last = max(merged[-1].last, span.last)
            merged[-1] = DateRange(merged[-1].first, last)
        else:
            merged.append(span)
    return tuple(merged)


def _instrument_to(instrument: Instrument) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "exchange": instrument.exchange,
        "currency": instrument.currency.value,
        "calendar": instrument.calendar,
        "asset_class": instrument.asset_class.value,
    }


def _instrument_from(data: dict[str, str]) -> Instrument:
    return Instrument(
        symbol=data["symbol"],
        exchange=data["exchange"],
        currency=Currency(data["currency"]),
        calendar=data["calendar"],
        asset_class=AssetClass(data["asset_class"]),
    )


def _distribution_from(instrument: Instrument, data: dict[str, str]) -> CashDistribution:
    return CashDistribution(
        instrument=instrument,
        ex_date=date.fromisoformat(data["ex_date"]),
        amount_per_share=Money(Decimal(data["amount"]), Currency(data["currency"])),
        kind=DistributionKind(data["kind"]),
    )


def _split_from(instrument: Instrument, data: dict[str, str]) -> Split:
    return Split(instrument, date.fromisoformat(data["ex_date"]), Decimal(data["ratio"]))


def _read_metadata(path: Path, raw: dict[bytes, bytes] | None) -> dict[str, Any]:
    if not raw or _METADATA_KEY not in raw:
        raise DataError(f"cache file {path} has no Tyche metadata")
    try:
        metadata: dict[str, Any] = json.loads(raw[_METADATA_KEY])
    except json.JSONDecodeError:
        raise DataError(f"cache file {path} has unreadable Tyche metadata") from None
    if metadata.get("format") != CACHE_FORMAT:
        raise DataError(
            f"cache file {path} is format {metadata.get('format')!r}; this version of Tyche "
            f"reads format {CACHE_FORMAT}. Delete it and it will be fetched again."
        )
    return metadata

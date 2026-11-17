"""A ``BarSource`` backed by yfinance, which reads Yahoo Finance's public endpoints.

Facts this adapter relies on, checked against yfinance 1.8.0 on 2026-11-17:

* ``history(auto_adjust=False)`` returns prices adjusted for splits but not for
  dividends. Yahoo has no truly unadjusted prices (ADR-0019).
* Daily rows are stamped at midnight, New York time. This adapter re-stamps each one at
  its session's close from the calendar, as the ``Bar`` contract requires.
* Dividends, capital-gain distributions and splits come back as columns on their
  ex-date rows. ``end`` is exclusive.
* Errors are raised only with ``yf.config.debug.hide_exceptions = False``; the older
  ``raise_errors`` option is deprecated. A range with no trading data then raises
  ``YFPricesMissingError``, and an unknown symbol an HTTP 404 (or ``YFTzMissingError``
  when the time-zone lookup fails first). The rate limit is ``YFRateLimitError`` or
  HTTP 429.

Terms: yfinance is not affiliated with Yahoo, and Yahoo's data is for personal use
only. Tyche keeps it in the private workspace and never redistributes it.
"""

import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche.adapters.data.cached_provider import SourceData
from tyche.core.domain import (
    Bar,
    CashDistribution,
    DataIssue,
    DataIssueKind,
    DistributionKind,
    Instrument,
    Money,
    PriceAdjustment,
    Split,
    Timeframe,
)
from tyche.core.ports import Calendar, DataError

SOURCE_NAME = "yfinance"
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class YahooRow:
    """One row of a Yahoo daily history, already turned into plain values."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    dividend: float = 0.0
    capital_gain: float = 0.0
    split: float = 0.0


class NoDataError(Exception):
    """The source has no trading data for the range. Not a failure."""


class UnknownSymbolError(Exception):
    """The source does not know the symbol. Asking again will not help."""


class TemporaryFailureError(Exception):
    """A network failure or rate limit. Worth retrying after a pause."""


type HistoryFetcher = Callable[[str, date, date], list[YahooRow]]
"""Fetches rows for a Yahoo ticker from ``start`` up to but not including ``end``.

Raises ``NoDataError``, ``UnknownSymbolError`` or ``TemporaryFailureError``; anything
else is treated as a permanent failure.
"""


class YFinanceSource:
    """Implements ``BarSource`` for instruments on the New York calendar.

    Args:
        calendars: Calendars by code, used to stamp each bar at its session's close.
        fetch: How rows are fetched. Defaults to yfinance itself; tests pass a fake.
        attempts: Tries per request before giving up on a temporary failure.
        backoff_seconds: Pause before the second try; doubled before each later one.
        sleep: How to pause. Tests pass a recorder so they never wait.
    """

    name = SOURCE_NAME
    adjustment = PriceAdjustment.SPLITS

    def __init__(
        self,
        calendars: Mapping[str, Calendar],
        *,
        fetch: HistoryFetcher | None = None,
        attempts: int = 3,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._calendars = dict(calendars)
        self._fetch = fetch or yfinance_fetcher()
        self._attempts = attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        ticker = yahoo_ticker(instrument)
        calendar = self._calendars.get(instrument.calendar)
        if calendar is None:
            raise DataError(f"no calendar {instrument.calendar!r} loaded for {instrument}")
        rows = self._fetch_with_retries(ticker, first, last + _ONE_DAY)
        return convert_rows(instrument, rows, calendar)

    def _fetch_with_retries(self, ticker: str, start: date, end: date) -> list[YahooRow]:
        pause = self._backoff_seconds
        for attempt in range(1, self._attempts + 1):
            try:
                return self._fetch(ticker, start, end)
            except NoDataError:
                return []
            except UnknownSymbolError:
                raise DataError(f"Yahoo Finance does not know the symbol {ticker!r}") from None
            except TemporaryFailureError as error:
                if attempt == self._attempts:
                    raise DataError(
                        f"Yahoo Finance failed for {ticker!r} after {attempt} attempts: {error}"
                    ) from None
                self._sleep(pause)
                pause *= 2
            except Exception as error:
                raise DataError(f"Yahoo Finance failed for {ticker!r}: {error}") from error
        raise AssertionError("unreachable")  # pragma: no cover


def yahoo_ticker(instrument: Instrument) -> str:
    """Yahoo's name for ``instrument``. Only US listings are supported for now.

    Yahoo writes share classes with a hyphen: ``BRK.B`` is ``BRK-B``. Toronto listings
    (``.TO``) arrive with the ``CA`` profile in Phase 4.
    """
    if instrument.calendar != "XNYS":
        raise DataError(
            f"the yfinance source does not support {instrument.calendar} listings yet "
            f"({instrument})"
        )
    return instrument.symbol.replace(".", "-")


def convert_rows(
    instrument: Instrument, rows: Iterable[YahooRow], calendar: Calendar
) -> SourceData:
    """Turn Yahoo rows into bars stamped at session closes, plus corporate actions.

    A row for a day the market was closed, or with prices that cannot be real, is
    reported as an issue instead of becoming a bar.
    """
    bars: list[Bar] = []
    distributions: list[CashDistribution] = []
    splits: list[Split] = []
    issues: list[DataIssue] = []

    for row in rows:
        session = calendar.session_on(row.day)
        if session is None:
            issues.append(
                DataIssue(
                    DataIssueKind.OFF_SESSION,
                    instrument,
                    row.day,
                    "dropped a row for a day the market was closed",
                )
            )
            continue
        try:
            bars.append(
                Bar(
                    instrument=instrument,
                    timeframe=Timeframe.D1,
                    timestamp=session.closes_at,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    adjustment=PriceAdjustment.SPLITS,
                )
            )
        except ValueError as error:
            issues.append(DataIssue(DataIssueKind.INVALID_BAR, instrument, row.day, str(error)))

        for amount, kind in (
            (row.dividend, DistributionKind.DIVIDEND),
            (row.capital_gain, DistributionKind.CAPITAL_GAIN),
        ):
            if _positive(amount):
                distributions.append(
                    CashDistribution(
                        instrument, row.day, Money(_exact(amount), instrument.currency), kind
                    )
                )
        if _positive(row.split):
            splits.append(Split(instrument, row.day, _exact(row.split)))

    return SourceData(tuple(bars), tuple(distributions), tuple(splits), tuple(issues))


def yfinance_fetcher(cache_dir: Path | None = None) -> HistoryFetcher:
    """The real fetcher. Imports yfinance only when called.

    ``cache_dir`` is where yfinance keeps its own small caches (time zones, cookies).
    Tyche points it into the workspace so nothing is written elsewhere.

    Turning yfinance's exceptions on is a process-wide setting; Tyche wants errors
    raised everywhere, so that is fine.
    """
    import yfinance as yf
    from curl_cffi.requests.exceptions import RequestException as CurlRequestError
    from requests.exceptions import RequestException as RequestsError

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # Tyche reports errors itself
    yf.config.debug.hide_exceptions = False
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))

    def fetch(ticker: str, start: date, end: date) -> list[YahooRow]:
        try:
            frame = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=True,
            )
        except yf.exceptions.YFPricesMissingError as error:
            raise NoDataError(str(error)) from error
        except yf.exceptions.YFTzMissingError as error:
            raise UnknownSymbolError(str(error)) from error
        except yf.exceptions.YFRateLimitError as error:
            raise TemporaryFailureError(str(error)) from error
        except (CurlRequestError, RequestsError) as error:
            raise classify_request_error(error) from error
        return rows_from_frame(frame)

    return fetch


def classify_request_error(error: Exception) -> Exception:
    """Decide whether an HTTP or network error is worth retrying.

    404 means Yahoo does not know the symbol. 429 and server errors are temporary, as is
    any failure with no HTTP response at all (a timeout, a dropped connection). Other
    HTTP errors are returned unchanged and treated as permanent.
    """
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 404:
        return UnknownSymbolError(str(error))
    if status is None or status == 429 or status >= 500:
        return TemporaryFailureError(str(error))
    return error


def rows_from_frame(frame: Any) -> list[YahooRow]:
    """Turn a yfinance history table into ``YahooRow`` values.

    Columns that a security never has (``Capital Gains`` for a stock) are treated as
    zero. The table's index is a date in New York time.
    """
    columns = set(frame.columns)

    def column(name: str) -> list[float]:
        if name not in columns:
            return [0.0] * len(frame)
        return [float(value) for value in frame[name].tolist()]

    days: list[date] = [stamp.date() for stamp in frame.index]
    values = {
        name: column(name)
        for name in (
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Dividends",
            "Capital Gains",
            "Stock Splits",
        )
    }
    return [
        YahooRow(
            day=day,
            open=values["Open"][i],
            high=values["High"][i],
            low=values["Low"][i],
            close=values["Close"][i],
            volume=values["Volume"][i],
            dividend=values["Dividends"][i],
            capital_gain=values["Capital Gains"][i],
            split=values["Stock Splits"][i],
        )
        for i, day in enumerate(days)
    ]


def _positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def _exact(value: float) -> Decimal:
    """The shortest decimal that prints as ``value``: 1.595, not 1.59499999999999997.

    Whole numbers lose their ``.0``, so a 10-for-1 split's ratio is ``10``.
    """
    exact = Decimal(repr(value))
    return exact.quantize(Decimal(1)) if exact == exact.to_integral_value() else exact

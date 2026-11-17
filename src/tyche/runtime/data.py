"""Wiring for fetching market data into the workspace cache.

This is composition-root code (ADR-0004): it picks the concrete calendar, source, cache
and clock, and hands back results in the core's own types.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.clocks import SystemClock
from tyche.adapters.data import (
    BarSource,
    CachedDataProvider,
    ParquetBarCache,
    YFinanceSource,
    yfinance_fetcher,
)
from tyche.config import KNOWN_EXCHANGES, TycheConfig
from tyche.core.domain import AssetClass, BarHistory, Instrument, MarketProfile
from tyche.core.ports import Calendar, Clock, DataError

CALENDAR_START = date(1990, 1, 1)
"""Earliest date Tyche loads calendars from, and so the earliest it can fetch."""

DEFAULT_FIRST = date(2000, 1, 1)
"""Where a fetch starts when no date is given: enough history for walk-forward testing."""


class FetchRequestError(ValueError):
    """The request cannot be made as asked, for example an exchange outside the profile."""


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """What happened for one instrument: its history, or why there is none."""

    instrument: Instrument
    history: BarHistory | None = None
    error: str | None = None


def instrument_for(
    symbol: str, exchange: str, asset_class: AssetClass, profile: MarketProfile
) -> Instrument:
    """Build an instrument from a symbol and an exchange, checked against the profile."""
    info = KNOWN_EXCHANGES.get(exchange)
    if info is None:
        known = ", ".join(sorted(KNOWN_EXCHANGES))
        raise FetchRequestError(f"unknown exchange {exchange!r}; known exchanges: {known}")
    if info.calendar not in profile.calendars or info.currency not in profile.cash_currencies:
        raise FetchRequestError(
            f"{info.name} ({exchange}) trades in {info.currency} on the {info.calendar} "
            f"calendar, which is not part of market profile {profile}"
        )
    try:
        return Instrument(symbol.upper(), exchange, info.currency, info.calendar, asset_class)
    except ValueError as error:
        raise FetchRequestError(str(error)) from None


def fetch_daily_histories(
    config: TycheConfig,
    instruments: Sequence[Instrument],
    first: date = DEFAULT_FIRST,
    last: date | None = None,
    *,
    source: BarSource | None = None,
    clock: Clock | None = None,
) -> list[FetchOutcome]:
    """Fetch, audit and cache daily bars for each instrument.

    Uses Yahoo Finance unless another ``source`` is given. One instrument failing does
    not stop the others; its outcome carries the error instead. ``last`` defaults to
    today; sessions that have not closed yet are never expected to have data.
    """
    clock = clock or SystemClock()
    last = last or clock.now().date()
    if first < CALENDAR_START:
        raise FetchRequestError(f"the earliest date Tyche can fetch from is {CALENDAR_START}")
    if first > last:
        raise FetchRequestError(f"empty date range: {first} is after {last}")

    calendar_end = max(last, clock.now().date())
    calendars: dict[str, Calendar] = {
        mic: ExchangeCalendarsCalendar(mic, first=CALENDAR_START, last=calendar_end)
        for mic in sorted({instrument.calendar for instrument in instruments})
    }
    data_dir = config.workspace.data_dir
    if source is None:
        source = YFinanceSource(calendars, fetch=yfinance_fetcher(data_dir / "yfinance-cache"))
    cache = ParquetBarCache(data_dir / "bars", source=source.name)
    provider = CachedDataProvider(source, cache, calendars, clock)

    outcomes: list[FetchOutcome] = []
    for instrument in instruments:
        try:
            outcomes.append(FetchOutcome(instrument, provider.daily_bars(instrument, first, last)))
        except DataError as error:
            outcomes.append(FetchOutcome(instrument, error=str(error)))
    return outcomes

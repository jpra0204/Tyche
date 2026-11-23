"""Seeded random walks with shocks: a ``DataProvider`` for whole-path tests.

Two years of the real New York calendar, 2022 and 2023, with walks that drift up and
now and then drop sharply at the open, so that dips are bought and stops are hit.
"""

import random
from datetime import date

from tests.support.market import QQQ, SPY
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import (
    AssetClass,
    Bar,
    BarHistory,
    Currency,
    Instrument,
    PriceAdjustment,
    Timeframe,
    audit_daily_bars,
)

TLT = Instrument("TLT", "XNAS", Currency.USD, "XNYS", AssetClass.ETF)
GLD = Instrument("GLD", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2020, 6, 1), last=date(2024, 3, 28))
FIRST, LAST = date(2022, 1, 3), date(2023, 12, 29)
WALKS = {SPY: (1, 0.0006), QQQ: (2, 0.0008), TLT: (3, 0.0001), GLD: (4, 0.0003)}
"""Per instrument: the seed of its walk and its daily drift."""


class Walks:
    """A ``DataProvider``: for each instrument a seeded walk from USD 100, with shocks.

    One session in a hundred falls 6% at the open, the kind of drop a stop is for.
    """

    def __init__(self) -> None:
        self._bars: dict[Instrument, list[Bar]] = {}
        for instrument, (seed, drift) in WALKS.items():
            draw = random.Random(seed)
            close = 100.0
            bars = []
            for session in NYSE.sessions_between(date(2020, 6, 1), LAST):
                shock = 0.94 if draw.random() < 0.01 else 1.0
                open_ = round(close * shock * (1 + draw.gauss(0, 0.004)), 2)
                close = round(open_ * (1 + draw.gauss(drift, 0.012)), 2)
                high = round(max(open_, close) * (1 + abs(draw.gauss(0, 0.004))), 2)
                low = round(min(open_, close) * (1 - abs(draw.gauss(0, 0.004))), 2)
                bars.append(
                    Bar(
                        instrument=instrument,
                        timeframe=Timeframe.D1,
                        timestamp=session.closes_at,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=5_000_000.0,
                        adjustment=PriceAdjustment.SPLITS,
                    )
                )
            self._bars[instrument] = bars

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        sessions = NYSE.sessions_between(first, last)
        days = {s.day for s in sessions}
        bars = [b for b in self._bars[instrument] if b.timestamp.date() in days]
        return audit_daily_bars(instrument, bars, sessions, adjustment=PriceAdjustment.SPLITS)

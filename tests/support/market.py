"""Builders for instruments, sessions and bars in tests.

Dates are New York winter sessions (January to early March), which close at 21:00 UTC
and open at 14:30 UTC. Using only winter dates keeps the helpers simple; the calendar
adapter's own tests cover summer time and half days.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from tyche.core.domain import (
    AssetClass,
    Bar,
    CashDistribution,
    Currency,
    DistributionKind,
    Instrument,
    Money,
    PriceAdjustment,
    Session,
    Split,
    Timeframe,
)

SPY = Instrument("SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
QQQ = Instrument("QQQ", "XNAS", Currency.USD, "XNYS", AssetClass.ETF)


def close_of(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC)


def session(day: date) -> Session:
    return Session(
        calendar="XNYS",
        day=day,
        opens_at=datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC),
        closes_at=close_of(day),
        is_half_day=False,
    )


def bar(
    day: date,
    close: float = 100.0,
    *,
    instrument: Instrument = SPY,
    adjustment: PriceAdjustment = PriceAdjustment.SPLITS,
    timeframe: Timeframe = Timeframe.D1,
    timestamp: datetime | None = None,
) -> Bar:
    """A plausible bar around ``close``: open 1% lower, high 2% higher, low 2% lower."""
    return Bar(
        instrument=instrument,
        timeframe=timeframe,
        timestamp=timestamp or close_of(day),
        open=close * 0.99,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
        volume=1_000_000.0,
        adjustment=adjustment,
    )


# Sessions of the New York Stock Exchange, 2 to 16 January 2024.
# 1 January (New Year) and 15 January (Martin Luther King Jr. Day) were holidays.
JANUARY_2024 = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10, 11, 12, 16)]


def dividend(day: date, amount: str, *, instrument: Instrument = SPY) -> CashDistribution:
    return CashDistribution(
        instrument, day, Money.of(amount, instrument.currency), DistributionKind.DIVIDEND
    )


def split(day: date, ratio: str, *, instrument: Instrument = SPY) -> Split:
    return Split(instrument, day, Decimal(ratio))

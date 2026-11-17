"""A Bar that exists is valid: bad market data cannot be constructed."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from tyche.core.domain import AssetClass, Bar, Currency, Instrument, PriceAdjustment, Timeframe

SPY = Instrument("SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)

# 2024-07-03 was a half day in New York: the session closed at 13:00 local, 17:00 UTC.
HALF_DAY_CLOSE = datetime(2024, 7, 3, 17, 0, tzinfo=UTC)

GOOD = Bar(
    instrument=SPY,
    timeframe=Timeframe.D1,
    timestamp=HALF_DAY_CLOSE,
    open=100.0,
    high=105.0,
    low=99.0,
    close=104.0,
    volume=1_000_000.0,
    adjustment=PriceAdjustment.SPLITS_AND_DIVIDENDS,
)


def test_holds_its_fields() -> None:
    assert GOOD.instrument is SPY
    assert GOOD.timeframe is Timeframe.D1
    assert GOOD.timestamp == HALF_DAY_CLOSE
    assert (GOOD.open, GOOD.high, GOOD.low, GOOD.close) == (100.0, 105.0, 99.0, 104.0)
    assert GOOD.volume == 1_000_000.0
    assert GOOD.adjustment is PriceAdjustment.SPLITS_AND_DIVIDENDS


def test_is_immutable() -> None:
    bar: Any = GOOD
    with pytest.raises(FrozenInstanceError):
        bar.close = 1.0


def test_a_flat_bar_with_no_volume_is_valid() -> None:
    flat = replace(GOOD, open=50.0, high=50.0, low=50.0, close=50.0, volume=0.0)
    assert flat.high == flat.low


def test_an_intraday_bar_is_the_same_kind_of_object() -> None:
    five_minute = replace(GOOD, timeframe=Timeframe.M5)
    assert five_minute.timeframe.is_intraday


class TestTimestamp:
    def test_rejects_a_naive_timestamp(self) -> None:
        naive = datetime(2024, 7, 3, 17, 0)  # noqa: DTZ001 - the mistake under test
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            replace(GOOD, timestamp=naive)

    def test_rejects_a_local_timezone(self) -> None:
        new_york_summer = timezone(timedelta(hours=-4))
        local = datetime(2024, 7, 3, 13, 0, tzinfo=new_york_summer)
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            replace(GOOD, timestamp=local)

    def test_accepts_any_zero_offset_timezone(self) -> None:
        zero_offset = datetime(2024, 7, 3, 17, 0, tzinfo=timezone(timedelta(0)))
        assert replace(GOOD, timestamp=zero_offset).timestamp == HALF_DAY_CLOSE


class TestPrices:
    @pytest.mark.parametrize("field", ["open", "high", "low", "close"])
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_rejects_non_positive_and_non_finite_prices(self, field: str, bad: float) -> None:
        fields: dict[str, Any] = {field: bad}
        with pytest.raises(ValueError, match=f"{field} must be a positive number"):
            replace(GOOD, **fields)

    def test_rejects_high_below_close(self) -> None:
        with pytest.raises(ValueError, match=r"high 103\.0 is below another price"):
            replace(GOOD, high=103.0)

    def test_rejects_high_below_open(self) -> None:
        with pytest.raises(ValueError, match="high"):
            replace(GOOD, open=106.0)

    def test_rejects_low_above_open(self) -> None:
        with pytest.raises(ValueError, match=r"low 101\.0 is above the open or the close"):
            replace(GOOD, low=101.0)

    def test_rejects_low_above_high(self) -> None:
        with pytest.raises(ValueError, match="high"):
            replace(GOOD, low=110.0)


class TestVolume:
    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_rejects_negative_and_non_finite_volume(self, bad: float) -> None:
        with pytest.raises(ValueError, match="volume must be zero or more"):
            replace(GOOD, volume=bad)


def test_error_message_identifies_the_bar() -> None:
    with pytest.raises(ValueError, match=r"SPY@ARCX 1d bar at 2024-07-03T17:00:00\+00:00"):
        replace(GOOD, close=-1.0)

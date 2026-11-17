"""Timeframe and Currency: small enums with a few rules."""

from datetime import timedelta

import pytest

from tyche.core.domain import Currency, Timeframe


def test_only_the_daily_timeframe_is_not_intraday() -> None:
    assert not Timeframe.D1.is_intraday
    assert all(tf.is_intraday for tf in Timeframe if tf is not Timeframe.D1)


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        (Timeframe.M1, timedelta(minutes=1)),
        (Timeframe.M5, timedelta(minutes=5)),
        (Timeframe.M15, timedelta(minutes=15)),
        (Timeframe.H1, timedelta(hours=1)),
    ],
)
def test_intraday_timeframes_have_a_fixed_duration(
    timeframe: Timeframe, expected: timedelta
) -> None:
    assert timeframe.duration == expected


def test_a_daily_bar_has_no_fixed_duration() -> None:
    # A session's length depends on the exchange and the date; ask the calendar.
    assert Timeframe.D1.duration is None


def test_every_intraday_timeframe_has_a_duration() -> None:
    assert all(tf.duration is not None for tf in Timeframe if tf.is_intraday)


def test_timeframes_round_trip_through_their_text_form() -> None:
    assert Timeframe("1d") is Timeframe.D1
    assert str(Timeframe.M5) == "5m"


def test_currency_is_its_iso_code() -> None:
    assert str(Currency.CAD) == "CAD"
    assert Currency("USD") is Currency.USD


def test_unknown_currency_is_rejected() -> None:
    with pytest.raises(ValueError, match="UDS"):
        Currency("UDS")

"""The shared indicators, against values worked out by hand."""

from datetime import date

import pytest

from tests.support.market import bar
from tyche.strategies.indicators import (
    IndicatorError,
    average_true_range,
    price_return,
    rsi,
    simple_average,
)


def test_simple_average_is_the_mean_of_the_last_closes() -> None:
    assert simple_average([1.0, 2.0, 3.0, 4.0], 2) == 3.5
    assert simple_average([1.0, 2.0, 3.0, 4.0], 4) == 2.5


def test_price_return_compares_the_last_close_with_one_sessions_back() -> None:
    assert price_return([100.0, 110.0, 121.0], 2) == pytest.approx(0.21)
    assert price_return([100.0, 110.0, 121.0], 1) == pytest.approx(0.10)


def test_rsi_uses_wilders_averages() -> None:
    # Changes +1, -0.5, +1. Seed: gain (1 + 0) / 2 = 0.5, loss (0 + 0.5) / 2 = 0.25.
    # Then +1: gain 0.5 + (1 - 0.5) / 2 = 0.75, loss 0.25 + (0 - 0.25) / 2 = 0.125.
    # RS = 6, RSI = 100 - 100 / 7.
    assert rsi([10.0, 11.0, 10.5, 11.5], 2) == pytest.approx(100 - 100 / 7)


def test_rsi_is_100_with_no_loss_and_50_with_no_change() -> None:
    assert rsi([1.0, 2.0, 3.0], 2) == 100.0
    assert rsi([5.0, 5.0, 5.0], 2) == 50.0


def test_rsi_falls_below_10_after_a_run_of_drops() -> None:
    # After rises, four drops of one: gain halves each time, loss closes in on 1.
    closes = [float(c) for c in range(104, 120)] + [118.0, 117.0, 116.0, 115.0]
    assert rsi(closes, 2) == pytest.approx(100 - 100 / (1 + 0.0625 / 0.9375))


def test_true_range_includes_a_gap_from_the_previous_close() -> None:
    # bar(): high = close * 1.02, low = close * 0.98.
    flat = [bar(date(2024, 1, d), 100.0) for d in (2, 3, 4)]
    assert average_true_range(flat, 2) == pytest.approx(4.0)

    gap = [bar(date(2024, 1, 2), 100.0), bar(date(2024, 1, 3), 110.0)]
    # high 112.2 minus the previous close 100 beats the day's own range of 4.4.
    assert average_true_range(gap, 1) == pytest.approx(12.2)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: simple_average([1.0], 2), "simple average needs 2 values, got 1"),
        (lambda: price_return([1.0, 2.0], 2), "price return needs 3 values, got 2"),
        (lambda: rsi([1.0, 2.0], 2), "RSI needs 3 values, got 2"),
        (lambda: simple_average([1.0], 0), "sessions must be at least 1"),
    ],
)
def test_a_short_window_is_refused(call: object, message: str) -> None:
    assert callable(call)
    with pytest.raises(IndicatorError, match=message):
        call()

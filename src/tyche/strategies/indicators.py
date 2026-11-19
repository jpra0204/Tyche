"""Price indicators the built-in strategies share, as plain functions of a window.

Each takes the bars or closes a strategy was handed (oldest first, the last one at the
decision time) and returns one number. They read nothing else, so a strategy built on
them stays a pure function of its context (ADR-0021).

Prices are ``float``, as bars are: these are signals, not money. A strategy turns a
price into ``Money`` only where it must, for a stop.

Definitions, written once:

* **Simple average**: the mean of the last ``sessions`` closes.
* **Price return**: the last close over the close ``sessions`` bars earlier, minus one.
  Prices are split-adjusted, not dividend-adjusted (ADR-0019), so this leaves out
  dividends: it understates the return of a fund that pays a high yield.
* **RSI** (Wilder's relative strength index): the average gain over the average loss
  of the close-to-close changes, as ``100 - 100 / (1 + gain / loss)``. Averages are
  Wilder's: the first is the simple mean of the window's first ``sessions`` changes,
  and each later change moves it by ``1 / sessions`` of the difference. With no loss
  it is 100; with no change at all, 50.
* **Average true range**: the simple mean of the last ``sessions`` true ranges. A true
  range is the largest of high minus low, high minus the previous close, and the
  previous close minus low: the day's range, gaps included.
"""

import math
from collections.abc import Sequence
from itertools import pairwise

from tyche.core.domain import Bar


class IndicatorError(ValueError):
    """The window is too short for the indicator, or a parameter makes no sense."""


def _require(values: Sequence[object], needed: int, what: str) -> None:
    if needed < 1:
        raise IndicatorError(f"{what}: sessions must be at least 1, got {needed}")
    if len(values) < needed:
        raise IndicatorError(f"{what} needs {needed} values, got {len(values)}")


def simple_average(closes: Sequence[float], sessions: int) -> float:
    """The mean of the last ``sessions`` closes."""
    _require(closes, sessions, "simple average")
    return math.fsum(closes[-sessions:]) / sessions


def price_return(closes: Sequence[float], sessions: int) -> float:
    """The return from the close ``sessions`` bars ago to the last close."""
    _require(closes, sessions + 1, "price return")
    return closes[-1] / closes[-1 - sessions] - 1


def rsi(closes: Sequence[float], sessions: int) -> float:
    """Wilder's relative strength index over ``sessions``, from 0 to 100."""
    _require(closes, sessions + 1, "RSI")
    changes = [after - before for before, after in pairwise(closes)]
    gain = math.fsum(max(change, 0.0) for change in changes[:sessions]) / sessions
    loss = math.fsum(max(-change, 0.0) for change in changes[:sessions]) / sessions
    for change in changes[sessions:]:
        gain += (max(change, 0.0) - gain) / sessions
        loss += (max(-change, 0.0) - loss) / sessions
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def average_true_range(bars: Sequence[Bar], sessions: int) -> float:
    """The mean true range of the last ``sessions`` bars."""
    _require(bars, sessions + 1, "average true range")
    ranges = [
        max(bar.high - bar.low, bar.high - before.close, before.close - bar.low)
        for before, bar in pairwise(bars[-sessions - 1 :])
    ]
    return math.fsum(ranges) / sessions

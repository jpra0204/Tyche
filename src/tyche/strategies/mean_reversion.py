"""MeanReversion: buy a short, sharp dip in an uptrend, sell the rebound, with a stop.

An example strategy (ADR-0027). It exists to exercise the framework's stop path
(a stop placed when the entry fills, resting at the broker, carried in the position),
not to make money, and its parameters were fixed before any backtest ran. Published
tests of this kind of strategy often find that a stop lowers its return, because it
sells at the worst moment of a dip.

The rule, for each of its instruments, each with an equal share of the budget, with
the defaults:

* **Buy** when the close is above its ``trend_sessions`` simple average (200: only
  dips in an uptrend) and its ``rsi_sessions`` RSI (2) is below ``entry_rsi`` (10).
* **Stop** at the entry decision's close minus ``stop_atrs`` (2.5) times the
  ``atr_sessions`` average true range (14), rounded down to the cent. The stop is
  placed when the entry fills and kept at that price for the life of the trade: the
  strategy reads it back from its position at every decision.
* **Sell** when the close rises above its ``exit_sessions`` simple average (5).

Two cases the stop cannot cover. A stop works from the session after the entry fills
(ADR-0023), so on the entry session the position is unprotected; if that session
closes at or below the stop, the strategy sells at the next open. And if a held
position has no stop resting (shares that came from another sleeve), it asks for one
from that day's close.
"""

from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal
from typing import Self

from pydantic import Field, StrictInt, model_validator

from tyche.core.domain import Bar, Instrument, Money, Target, Timeframe
from tyche.core.pipeline.signals import StrategyContext
from tyche.strategies.indicators import average_true_range, rsi, simple_average
from tyche.strategies.registry import (
    ExactDecimal,
    InstrumentLookup,
    InstrumentParameters,
    Parameters,
    Plugin,
)

_CENT = Decimal("0.01")


class MeanReversion:
    """Buys dips in ``instruments`` and sells the rebound, each with a protective stop.

    Args:
        instruments: What it trades, each with an equal share of the budget.
        trend_sessions: Sessions of the average the close must be above to buy.
        rsi_sessions: Sessions of the RSI.
        entry_rsi: Buy only when the RSI is below this, from 0 to 100.
        exit_sessions: Sessions of the average the close must rise above to sell.
        atr_sessions: Sessions of the average true range the stop is measured in.
        stop_atrs: How many average true ranges below the close the stop goes.
        strategy_id: The instance's identifier.
    """

    version = "1"
    timeframe = Timeframe.D1

    def __init__(
        self,
        instruments: Sequence[Instrument],
        *,
        trend_sessions: int = 200,
        rsi_sessions: int = 2,
        entry_rsi: Decimal = Decimal(10),
        exit_sessions: int = 5,
        atr_sessions: int = 14,
        stop_atrs: Decimal = Decimal("2.5"),
        strategy_id: str = "mean_reversion",
    ) -> None:
        if not instruments or len(set(instruments)) != len(instruments):
            raise ValueError("mean reversion: list each instrument once, at least one")
        if min(trend_sessions, rsi_sessions, exit_sessions, atr_sessions) < 1:
            raise ValueError("mean reversion: sessions must be at least 1")
        if not 0 < entry_rsi < 100:
            raise ValueError(
                f"mean reversion: entry_rsi must be between 0 and 100, got {entry_rsi}"
            )
        if not stop_atrs > 0:
            raise ValueError(f"mean reversion: stop_atrs must be above 0, got {stop_atrs}")
        self.instruments = tuple(instruments)
        self.trend_sessions = trend_sessions
        self.rsi_sessions = rsi_sessions
        self.entry_rsi = entry_rsi
        self.exit_sessions = exit_sessions
        self.atr_sessions = atr_sessions
        self.stop_atrs = stop_atrs
        self.strategy_id = strategy_id
        self.lookback = max(trend_sessions, rsi_sessions + 1, exit_sessions, atr_sessions + 1)
        self._weight = Decimal(1) / Decimal(len(instruments))

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        return tuple(
            self._decide_one(context, instrument)
            for instrument in context.instruments
            if instrument in self.instruments
        )

    def _decide_one(self, context: StrategyContext, instrument: Instrument) -> Target:
        bars = context.history.bars(instrument, self.timeframe)
        closes = [bar.close for bar in bars]
        close = Decimal(repr(closes[-1]))
        held = context.position(instrument)

        if held is not None:
            if closes[-1] > simple_average(closes, self.exit_sessions):
                return self._out(
                    instrument, f"close above its {self.exit_sessions}-session average"
                )
            stop = held.stop_price
            if stop is None:
                stop = self._stop(instrument, close, bars)
            if stop is None or stop.amount >= close:
                return self._out(instrument, "close at or below the stop before it could work")
            return Target(instrument, self._weight, "hold the dip until it rebounds", stop)

        if closes[-1] <= simple_average(closes, self.trend_sessions):
            return self._out(
                instrument, f"close at or below its {self.trend_sessions}-session average"
            )
        strength = rsi(closes, self.rsi_sessions)
        if strength >= float(self.entry_rsi):
            return self._out(instrument, f"RSI({self.rsi_sessions}) {strength:.1f}, no dip")
        stop = self._stop(instrument, close, bars)
        if stop is None:
            return self._out(instrument, "no room for a stop above zero")
        reason = (
            f"RSI({self.rsi_sessions}) {strength:.1f} in an uptrend; stop "
            f"{self.stop_atrs} x ATR({self.atr_sessions}) below the close"
        )
        return Target(instrument, self._weight, reason, stop)

    def _stop(self, instrument: Instrument, close: Decimal, bars: Sequence[Bar]) -> Money | None:
        atr = average_true_range(bars, self.atr_sessions)
        price = (close - self.stop_atrs * Decimal(repr(atr))).quantize(_CENT, ROUND_FLOOR)
        if price <= 0 or price >= close:
            return None
        return Money(price, instrument.currency)

    @staticmethod
    def _out(instrument: Instrument, reason: str) -> Target:
        return Target(instrument, Decimal(0), reason)


class MeanReversionParameters(Parameters):
    """``[parameters]`` of a ``mean_reversion`` strategy file."""

    instruments: tuple[InstrumentParameters, ...] = Field(min_length=1)
    trend_sessions: StrictInt = Field(200, ge=1)
    rsi_sessions: StrictInt = Field(2, ge=1)
    entry_rsi: ExactDecimal = Field(Decimal(10), gt=0, lt=100)
    exit_sessions: StrictInt = Field(5, ge=1)
    atr_sessions: StrictInt = Field(14, ge=1)
    stop_atrs: ExactDecimal = Field(Decimal("2.5"), gt=0)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        listed = [(entry.symbol, entry.exchange) for entry in self.instruments]
        if len(set(listed)) != len(listed):
            raise ValueError("instruments: an instrument is listed more than once")
        return self


def _build(
    strategy_id: str, parameters: MeanReversionParameters, lookup: InstrumentLookup
) -> MeanReversion:
    return MeanReversion(
        tuple(entry.build(lookup) for entry in parameters.instruments),
        trend_sessions=parameters.trend_sessions,
        rsi_sessions=parameters.rsi_sessions,
        entry_rsi=parameters.entry_rsi,
        exit_sessions=parameters.exit_sessions,
        atr_sessions=parameters.atr_sessions,
        stop_atrs=parameters.stop_atrs,
        strategy_id=strategy_id,
    )


PLUGIN = Plugin("mean_reversion", MeanReversionParameters, _build)

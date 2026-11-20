"""TrendRotation: once a month, hold the ETFs that have risen most, if they are in an uptrend.

An example strategy (ADR-0027). It exists to exercise the framework (several
instruments, a monthly rebalance, positions that change hands), not to make money,
and its parameters were fixed before any backtest ran.

The rule, with the defaults:

* **When.** At the close of the first session of each month: the first decision whose
  bar falls in a different month from the bar before it. The orders fill at the next
  open. On every other day it keeps what it holds.
* **Rank.** Every one of its instruments that is offered (eligible, with a full
  window) by its ``momentum_sessions`` price return (126 sessions, about six months),
  highest first; ties by symbol.
* **Hold.** The top ``holdings`` (3), each with ``1 / holdings`` of the budget, but
  only if its close is above its ``trend_sessions`` simple average (200). A top
  instrument below its average gets nothing: its share stays in cash.

Known biases: returns are price only (ADR-0019), so funds that
pay a high yield (bonds, REITs) rank lower than their total return would put them; and
an instrument not offered at a rebalance (a data problem, or still warming up) keeps
any position it has until the next rebalance that offers it, so for a month the
strategy can hold more than ``holdings`` instruments.

Between rebalances it asks for the same weight for each holding. Execution's rebalance
band keeps a holding as it is unless it drifts more than the band from that weight
(ADR-0023).
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Self

from pydantic import Field, StrictInt, model_validator

from tyche.core.domain import Instrument, Target, Timeframe
from tyche.core.pipeline.signals import StrategyContext
from tyche.strategies.indicators import price_return, simple_average
from tyche.strategies.registry import InstrumentLookup, InstrumentParameters, Parameters, Plugin


class TrendRotation:
    """Holds the ``holdings`` best performers of ``instruments``, rebalanced monthly.

    Args:
        instruments: What it may hold. At least ``holdings``, each once.
        holdings: How many to hold at most, in equal shares of the budget.
        momentum_sessions: Sessions of price return to rank on.
        trend_sessions: Sessions of the average a holding's close must be above.
        strategy_id: The instance's identifier.
    """

    version = "1"
    timeframe = Timeframe.D1

    def __init__(
        self,
        instruments: Sequence[Instrument],
        *,
        holdings: int = 3,
        momentum_sessions: int = 126,
        trend_sessions: int = 200,
        strategy_id: str = "trend_rotation",
    ) -> None:
        if len(set(instruments)) != len(instruments):
            raise ValueError("trend rotation: an instrument is listed more than once")
        if not 1 <= holdings <= len(instruments):
            raise ValueError(
                f"trend rotation: holdings must be from 1 to the {len(instruments)} "
                f"instruments listed, got {holdings}"
            )
        if momentum_sessions < 1 or trend_sessions < 1:
            raise ValueError("trend rotation: sessions must be at least 1")
        self.instruments = tuple(instruments)
        self.holdings = holdings
        self.momentum_sessions = momentum_sessions
        self.trend_sessions = trend_sessions
        self.strategy_id = strategy_id
        self.lookback = max(momentum_sessions + 1, trend_sessions, 2)
        self._weight = Decimal(1) / Decimal(holdings)

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        offered = [i for i in context.instruments if i in self.instruments]
        if not offered:
            return ()
        if not self._first_session_of_month(context, offered[0]):
            return self._keep(context, offered)
        return self._rebalance(context, offered)

    def _first_session_of_month(self, context: StrategyContext, instrument: Instrument) -> bool:
        last, before = context.history.bars(instrument, self.timeframe)[-1:-3:-1]
        return last.timestamp.date().month != before.timestamp.date().month

    def _keep(self, context: StrategyContext, offered: Sequence[Instrument]) -> Sequence[Target]:
        return tuple(
            Target(i, self._weight, "hold until the next monthly rebalance")
            for i in offered
            if context.position(i) is not None
        )

    def _rebalance(
        self, context: StrategyContext, offered: Sequence[Instrument]
    ) -> Sequence[Target]:
        momentum = {
            i: price_return(context.history.closes(i, self.timeframe), self.momentum_sessions)
            for i in offered
        }
        ranked = sorted(offered, key=lambda i: (-momentum[i], i.symbol, i.exchange))
        targets: list[Target] = []
        for rank, instrument in enumerate(ranked, start=1):
            closes = context.history.closes(instrument, self.timeframe)
            standing = (
                f"rank {rank} of {len(ranked)} by {self.momentum_sessions}-session return "
                f"({momentum[instrument]:+.1%})"
            )
            if rank > self.holdings:
                targets.append(Target(instrument, Decimal(0), standing))
            elif closes[-1] > simple_average(closes, self.trend_sessions):
                reason = f"{standing}, close above its {self.trend_sessions}-session average"
                targets.append(Target(instrument, self._weight, reason))
            else:
                reason = (
                    f"{standing}, but close at or below its {self.trend_sessions}-session "
                    "average: its share stays in cash"
                )
                targets.append(Target(instrument, Decimal(0), reason))
        return tuple(targets)


class TrendRotationParameters(Parameters):
    """``[parameters]`` of a ``trend_rotation`` strategy file."""

    instruments: tuple[InstrumentParameters, ...] = Field(min_length=1)
    holdings: StrictInt = Field(3, ge=1)
    momentum_sessions: StrictInt = Field(126, ge=1)
    trend_sessions: StrictInt = Field(200, ge=1)

    @model_validator(mode="after")
    def _holdings_fit(self) -> Self:
        listed = [(entry.symbol, entry.exchange) for entry in self.instruments]
        if len(set(listed)) != len(listed):
            raise ValueError("instruments: an instrument is listed more than once")
        if self.holdings > len(self.instruments):
            raise ValueError(
                f"holdings: {self.holdings} is more than the {len(self.instruments)} "
                "instruments listed"
            )
        return self


def _build(
    strategy_id: str, parameters: TrendRotationParameters, lookup: InstrumentLookup
) -> TrendRotation:
    return TrendRotation(
        tuple(entry.build(lookup) for entry in parameters.instruments),
        holdings=parameters.holdings,
        momentum_sessions=parameters.momentum_sessions,
        trend_sessions=parameters.trend_sessions,
        strategy_id=strategy_id,
    )


PLUGIN = Plugin("trend_rotation", TrendRotationParameters, _build)

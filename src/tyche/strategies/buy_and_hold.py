"""BuyAndHold: the benchmark. Puts the whole budget in one instrument and keeps it there.

Every strategy must beat this after costs to be worth running (brief, section 1). For
the ``US`` profile the instrument is an index ETF such as SPY.

It needs only the current bar (``lookback = 1``). It targets its instrument whenever
the instrument is eligible; on a cycle when it is not (a data problem, say), it
returns nothing, and the position is kept rather than sold (ADR-0021).
"""

from collections.abc import Sequence
from decimal import Decimal

from pydantic import StrictStr

from tyche.core.domain import AssetClass, Instrument, Target, Timeframe
from tyche.core.pipeline.signals import StrategyContext
from tyche.strategies.registry import InstrumentLookup, Parameters, Plugin


class BuyAndHold:
    """Holds ``instrument`` with the strategy's whole budget.

    Args:
        instrument: What to hold.
        strategy_id: The instance's identifier.
    """

    version = "1"
    timeframe = Timeframe.D1
    lookback = 1

    def __init__(self, instrument: Instrument, *, strategy_id: str = "buy_and_hold") -> None:
        self.instrument = instrument
        self.strategy_id = strategy_id

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        if self.instrument not in context.instruments:
            return ()
        held = context.position(self.instrument)
        if held is None:
            reason = f"buy and hold {self.instrument}: enter"
        else:
            reason = f"buy and hold {self.instrument}: hold since {held.entry_date.isoformat()}"
        return (Target(self.instrument, Decimal(1), reason),)


class BuyAndHoldParameters(Parameters):
    """``[parameters]`` of a ``buy_and_hold`` strategy file."""

    symbol: StrictStr
    exchange: StrictStr
    asset_class: AssetClass


def _build(
    strategy_id: str, parameters: BuyAndHoldParameters, lookup: InstrumentLookup
) -> BuyAndHold:
    instrument = lookup(parameters.symbol, parameters.exchange, parameters.asset_class)
    return BuyAndHold(instrument, strategy_id=strategy_id)


PLUGIN = Plugin("buy_and_hold", BuyAndHoldParameters, _build)

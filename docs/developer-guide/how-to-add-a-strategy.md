# How to add a strategy

A strategy is one class that turns a `StrategyContext` into targets. It needs no change to the core. The contract is [ADR-0021](../adr/0021-strategies-see-a-window-handed-in.md); this page is the practical version.

*Written in PR 12; the config and registry steps added in PR 13 ([ADR-0022](../adr/0022-portfolio-targets-as-weights-in-sleeves.md)).*

## 1. Write the class

Put a built-in strategy in `src/tyche/strategies/<name>.py`. It may import only `tyche.core.domain`, `tyche.core.events` and `tyche.core.pipeline.signals`; the import contracts fail CI if it reaches risk, execution, the engine, the simulator or a port.

```python
from collections.abc import Sequence
from decimal import Decimal

from tyche.core.domain import Instrument, Target, Timeframe
from tyche.core.pipeline.signals import StrategyContext


class AboveAverage:
    """Holds an instrument while its close is above its 50-day average."""

    version = "1"  # change whenever the logic changes
    timeframe = Timeframe.D1  # daily only in Phase 1
    lookback = 50  # bars needed per instrument

    def __init__(self, instrument: Instrument, *, strategy_id: str = "above_average") -> None:
        self.instrument = instrument
        self.strategy_id = strategy_id

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        if self.instrument not in context.instruments:
            return ()  # not offered this cycle: any position is kept, not sold
        closes = context.history.closes(self.instrument, self.timeframe)
        if closes[-1] > sum(closes) / len(closes):
            return (Target(self.instrument, Decimal(1), "close above its 50-day average"),)
        return (Target(self.instrument, Decimal(0), "close below its 50-day average"),)
```

## 2. Know the rules

| Rule | Why |
|---|---|
| Keep no state between calls; the same context must give the same targets | A restart in paper or live must behave exactly like the backtest |
| Use `context.positions` (or `context.position(instrument)`) to tell an entry from a hold | It is the only memory a strategy has; it is empty until execution exists (PR 14) |
| Target only instruments in `context.ranked`, each at most once | The others failed the universe rules or are still warming up |
| Weights are `Decimal` from 0 to 1 and add up to at most 1 | They are fractions of the strategy's own budget; the rest is cash |
| A stop, if any, is below the instrument's last close | Tyche is long only; a stop at or above the price would trigger at once |
| Leaving out an offered instrument means zero; a held instrument that is not offered keeps its position | So a data gap never sells by accident |

Instruments with fewer bars than `lookback` are listed in `context.warming_up` and have no window: `context.history.bars(...)` raises for them. Breaking any rule, or raising, makes the strategy fail for that cycle: it is listed in `SignalsReadyEvent.failed`, publishes nothing, and the other strategies carry on.

On stops: a target with a stop is sized by risk per trade, one without a stop is not ([ADR-0006](../adr/0006-target-positions-with-optional-stops.md)). Prices in a backtest are split-adjusted to the fetch date, so a stop computed before a later split is on the adjusted basis; that is consistent with the simulated fills ([backtesting internals](backtesting-internals.md#4-what-a-strategy-sees)).

## 3. Test it without the engine

Build a context by hand, call `decide`, check the targets. No bus, clock or data needed. `tests/strategies/test_buy_and_hold.py` is the worked example:

```python
view = HistoryView(as_of, {(SPY, Timeframe.D1): bars}, lookback=50)
context = StrategyContext(as_of, ranked, warming_up=(), history=view)
assert strategy.decide(context) == (Target(SPY, Decimal(1), "..."),)
```

Then add it to an end-to-end test like `tests/integration/test_replay_to_signals.py` to see it on the real calendar.

## 4. Register it and give it parameters

A workspace names a plugin and gives its parameters in `config/strategies/<id>.toml`. Declare them as a strict model, with a build function and a `Plugin`, next to the class:

```python
from pydantic import StrictStr

from tyche.core.domain import AssetClass
from tyche.strategies.registry import InstrumentLookup, Parameters, Plugin


class AboveAverageParameters(Parameters):  # unknown keys are refused
    symbol: StrictStr
    exchange: StrictStr
    asset_class: AssetClass


def _build(
    strategy_id: str, parameters: AboveAverageParameters, lookup: InstrumentLookup
) -> AboveAverage:
    instrument = lookup(parameters.symbol, parameters.exchange, parameters.asset_class)
    return AboveAverage(instrument, strategy_id=strategy_id)


PLUGIN = Plugin("above_average", AboveAverageParameters, _build)
```

`lookup` builds the instrument and checks it against the market profile; a strategy never reads the config itself. Then add `PLUGIN` to `PLUGINS` in `src/tyche/strategies/__init__.py`, and test it as `tests/strategies/test_registry.py` does.

## 5. Configure it

In the workspace, give it a budget and a file of the same name:

```toml
# config/tyche.toml
[strategies]
buy_and_hold = "0.5"
above_average = "0.5"
```

```toml
# config/strategies/above_average.toml
plugin = "above_average"

[parameters]
symbol = "QQQ"
exchange = "XNAS"
asset_class = "etf"
```

`tyche config check` builds every strategy and names the file and key of any mistake. Its weights are fractions of its budget; how budgets combine is in [backtesting internals](backtesting-internals.md#5-how-strategies-share-the-account).

If pandas makes the maths clearer, use it inside `decide`; a helper that turns a history view into a frame arrives with the first strategy that needs one (PR 18).

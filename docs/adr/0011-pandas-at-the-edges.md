# ADR-0011: pandas as the only dataframe library, kept at the edges

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

The brief allows pandas or polars for data. Tyche needs tabular data in three places: fetching and caching bars, computing indicators inside strategies, and computing metrics for reports. The event-driven core itself moves single events, not tables.

## Decision

1. **pandas is the one dataframe library.** polars is not adopted.
2. **Events, domain objects and port signatures never contain a dataframe.** They use Tyche's own types (`Bar`, `Instrument`, `Money`).
3. **pandas is used at the edges:** data adapters and the Parquet cache, backtest metrics and reports, and indicator maths inside a strategy.
4. **How a strategy sees history is decided in Phase 1.** A strategy needs a window of past bars. The likely design is a read-only history view that can hand out a pandas frame; the strategy interface design will settle it and update this record. *Settled by [ADR-0021](0021-strategies-see-a-window-handed-in.md): the view returns Tyche's own types, and a helper in `tyche.strategies` turns it into a frame.*

## Alternatives considered

- **polars.** Faster and stricter about types. But every edge library we plan to use (yfinance, exchange_calendars, backtesting.py, vectorbt) speaks pandas, so polars would mean converting at every boundary and learning two APIs. Speed is not a constraint for daily bars.
- **Both.** Two ways to do everything.
- **No dataframe library in strategies at all.** Pure, but rolling means and ranks by hand are slower to write and easier to get wrong.

## Consequences

- One tabular API across the project.
- pandas does not appear in the core's event and port contracts, so replacing it later would touch the edges only.
- pandas typing is weaker than the rest of the code base. `pandas-stubs` will be added with pandas in Phase 1, and frames will be converted to domain types as soon as they cross into the core.

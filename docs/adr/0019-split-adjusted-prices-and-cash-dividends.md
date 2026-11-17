# ADR-0019: Split-adjusted prices, with dividends as cash events

- **Status:** Accepted (Pablo, 2026-11-17)
- **Date:** 2026-11-17

## Context

Building the cache in PR 5 raised a question for PR 6: free sources can return prices adjusted for dividends, and that adjustment is recomputed whenever a dividend is paid. Checking yfinance 1.8.0 directly on 2026-11-17 showed:

1. **There are no truly unadjusted prices.** NVDA's close on 7 June 2024, before its 10-for-1 split, comes back as $120.89 with `auto_adjust=False`; it actually traded near $1,208.89. Volume is rescaled too. Yahoo's "unadjusted" means adjusted for splits, not for dividends.
2. **Dividend adjustment rewrites history.** SPY's dividend-adjusted close for 12 March 2024 was 0.968 times its split-adjusted close when fetched in November 2026. Every later dividend lowers that ratio again.
3. **Dividends and splits are reported separately** on their ex-dates, alongside the bars.

A cache that stored dividend-adjusted prices and appended new ones would quietly mix adjustment bases in one series.

## Decision

1. **Prices are stored adjusted for splits only.** That basis does not change when a dividend is paid, so cached bars stay valid.
2. **Every bar states its adjustment basis**: `PriceAdjustment.NONE`, `SPLITS` or `SPLITS_AND_DIVIDENDS`. It replaces the earlier yes/no flag, which could not describe Yahoo's data truthfully. Mixing bases in one series is an error.
3. **Dividends and capital-gain distributions are `CashDistribution` events**: an amount per share, in the instrument's currency, on an ex-date. **Splits are `Split` events** with a ratio. Both are cached with the bars and returned in every `BarHistory` for its window.
4. **A new split triggers a full refetch.** A split rewrites every earlier split-adjusted price. When a fetch reports a split the cache has not seen, and the cache holds bars from before it, the instrument's whole cached history is fetched again and replaces the old one. If that refetch returns nothing, it is an error rather than a half-updated cache.
5. **The simulated broker will credit distributions as cash** (PR 10), to whoever holds the shares at the close before the ex-date.

## Alternatives considered

- **Store fully adjusted prices and refetch on every new dividend or split.** Least code, and total return comes for free. But cached prices shift every quarter, so an old backtest cannot be reproduced exactly, and dividends never appear as cash in the account or the tax export.
- **Both bases, chosen per run.** The most flexible, and the most to build and test before anything uses it. A fully adjusted series can be derived later from split-adjusted prices plus distributions if research needs it.

## Consequences

- Backtest returns include dividends only if the simulated broker credits them. Until PR 10, a strategy's return and the buy-and-hold benchmark's are both price-only, so they stay comparable.
- The ex-date is known but the payment date is not: Yahoo does not report it. Crediting at the ex-date is an approximation, and a cash account may not be able to spend the money for some weeks. PR 10 will document the rule it uses.
- Dividends on US securities paid to a Canadian resident are subject to withholding tax. The rate and how IBKR applies it must be checked before the US profile models it (Phase 2 or 4).
- The cache format is now version 2. Version 1 files were only ever written by tests.

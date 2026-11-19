# ADR-0027: Two example strategies, with their rules fixed before any backtest

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Phase 1, PR 18 adds the first strategies besides buy-and-hold: "an ETF trend rotation and a mean-reversion strategy that uses a stop". They have two jobs. They exercise parts of the framework that buy-and-hold never touches: several instruments, a rebalance on a calendar, positions that change hands, and a protective stop from target to fill. And they give the measurement tools still to come (the report, walk-forward, parameter sweeps) something to measure.

They are not meant to make money, and they must not quietly become the start of overfitting. A rule tuned on the same history it is then judged on looks better than it is. So the rules and every parameter were chosen from textbook defaults and agreed **before** any backtest ran. They were then backtested once, and nothing was changed after seeing the result.

## Decision

1. **Nine ETFs across asset classes** are the market profile's candidates and the rotation's choice: SPY, QQQ (US large caps), IWM (US small caps), EFA (developed markets outside North America), EEM (emerging markets), TLT and IEF (long and intermediate Treasuries), GLD (gold) and VNQ (US REITs). Bonds and gold give a rotation somewhere to go when stocks fall. Listing exchanges were checked on Yahoo Finance on 2026-11-19: QQQ, TLT and IEF on Nasdaq (`XNAS`), the others on NYSE Arca (`ARCX`).
2. **Trend rotation** (`trend_rotation`): relative and absolute momentum. At the close of each month's first session, rank the ETFs by their 126-session price return. Hold the top 3, a third of the budget each, but only those whose close is above their 200-session simple average; a top ETF below its average leaves its third in cash. Between rebalances, keep what is held.
3. **Mean reversion** (`mean_reversion`): a short-term dip buy on SPY and QQQ, half the budget each. Buy when the close is above its 200-session simple average and Wilder's RSI over 2 sessions is below 10. Sell when the close rises above its 5-session simple average. At entry, set a stop at the close minus 2.5 times the 14-session average true range, rounded down to the cent, and keep it at that price for the life of the trade.

## Implementation choices made in PR 18, for review there

- **Strategies keep no memory, so the rules are written to need none** (ADR-0021). The rotation knows a month has turned because the bar before the last one in its window is from another month. The mean reversion keeps its stop at the broker and reads it back from its position at every decision (`StrategyPosition.stop_price`). Learning note: [strategies without memory](../learning/strategies-without-memory.md).
- **Indicators are plain functions in `tyche.strategies.indicators`**, on `float` prices: simple average, price return, Wilder's RSI, and the average true range as a simple mean of true ranges. Their definitions are in the module's docstring. No pandas: a few lines of Python are clearer than a dataframe for windows of 200 numbers.
- **Between rebalances the rotation asks for the same weight** for each holding. Execution's 10% rebalance band (ADR-0023) then keeps the holding as it is, unless it drifts further than that. On the 2005 to 2023 run, all 353 fills that opened or closed a position came at the open after a month's first session.
- **An ETF not offered at a rebalance keeps any position it has.** This happens when an ETF is excluded for a data problem, or still warming up. It is the framework's rule that a data gap never sells (ADR-0021). For up to a month, the rotation can then hold more than three ETFs.
- **The mean reversion's stop cannot cover the entry session.** A stop works from the session after its entry fills (ADR-0023). If that session closes at or below the stop, the strategy sells at the next open. If a held position has no stop resting (shares crossed in from another sleeve), it asks for one from that day's close.
- **Parameters are in the strategy files,** with the agreed values as defaults, checked strictly: sessions at least 1, holdings at most the number of ETFs, each instrument once, decimals written as strings. Both files ship in new workspaces **without a budget**, so a new workspace still runs buy-and-hold alone.
- **Returns are price only.** Prices are split-adjusted, with dividends as cash (ADR-0019), so the rotation ranks funds that pay a high yield (TLT, IEF, VNQ) a little lower than their total return would.

## Checked on real data

Yahoo data from 2004 to 2023 in a scratch workspace, each strategy alone with USD 10,000 from 2005-01-03 to 2023-12-29. These runs were made after the rules were fixed and changed nothing:

| | Trend rotation | Mean reversion | SPY total return (benchmark) |
|---|---|---|---|
| Final equity | 30,049 USD | 12,735 USD | |
| CAGR | 5.97% | 1.28% | 9.59% |
| Volatility | 13.70% | 5.25% | 19.31% |
| Sharpe (rf 0) | 0.49 | 0.27 | 0.57 |
| Max drawdown | 29.68% | 12.44% | 55.20% |
| Exposure | 86.02% | 10.18% | 100% |
| Turnover | 5.90 a year | 16.99 a year | |
| Costs | 544 USD | 698 USD | |
| Closed trades, win rate | 175, 47% | 328, 63%; 41 closed by the stop | |

No free riding in either run. The only data issues were the sessions before GLD (November 2004) and VNQ (September 2004) existed, all inside the warm-up.

Neither strategy beats holding SPY, which is the brief's bar: beat buy-and-hold after costs, adjusted for risk. The rotation's worst fall was 29.7% (August 2018 to March 2020), against the benchmark's 55.2% (October 2007 to March 2009), and it paid for that with a lower return. The mean reversion is invested a tenth of the time, so its low return and low drawdown both come mostly from sitting in cash. Its costs (698 USD) are more than a quarter of what it made (2,735 USD): on a small account, costs weigh heavily on a strategy that trades often, which PR 22 (minimum viable capital) measures.

## Alternatives considered

- **Four ETFs (SPY, QQQ, TLT, GLD), or US equity only.** Fewer fetches; less diversification, and, for equity only, nowhere to go in a bear market but cash.
- **Ranking on 12-month returns, or holding only the single best ETF.** Fewer trades, but slower to turn, or concentrated in one fund.
- **A 5% fixed stop, or Bollinger-band entries.** Simpler or equally standard; the ATR stop scales with volatility, so it is the same distance in calm and volatile markets.
- **Picking parameters by trying several and keeping the best.** Rejected outright: that is overfitting, and PR 21 is where trials will be counted and deflated.

## Consequences

- Every new workspace lists nine candidates, so a backtest needs all nine fetched, even one that trades only SPY. Two `tyche data fetch` commands do it (one per exchange). Existing workspaces keep their own list until it is edited.
- The report (PR 19), walk-forward (PR 20) and parameter sweeps (PR 21) have three strategies to work on, each a different shape: one position always held, three positions rotated monthly, short trades with stops.
- These results are the strategies' first trial. A later change to a rule or a parameter is a new trial, and is recorded as one.

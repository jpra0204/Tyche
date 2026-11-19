# ADR-0025: Metrics: measured against the benchmark's total return, with a zero risk-free rate

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Phase 1, PR 16 adds the metrics the brief asks for: CAGR, volatility, Sharpe, Sortino, maximum drawdown, turnover, win rate and exposure, all compared with the benchmark. Two questions decided what the numbers mean:

1. **What is the benchmark?** Tyche's own buy-and-hold strategy is the obvious candidate, but it is an easy bar. It pays commissions, keeps the price buffer in cash, and holds dividends as cash until the position falls more than the 10% rebalance band below its target. On SPY from 2005 to 2023 it ends with about 9% in cash. A strategy compared with it is helped by that cash drag before it has done anything.
2. **What risk-free rate do Sharpe and Sortino use?** The simulator pays no interest on cash, so a strategy's idle cash earns 0% in a backtest. Short-term US rates over 2005 to 2023 went from about 5% to near zero and back.

## Decision

1. **The benchmark is the total return of the market profile's index ETF.** It is computed from cached data, not simulated. At the first session close of the run, the run's starting equity buys the ETF at that close. Every distribution is reinvested at the close of its ex-date, with no costs and no cash. This is what simply holding the ETF pays, and it is the harder, honest bar. The ETF is named in a new `[benchmark]` table of `config/markets/<NAME>.toml` (`SPY` on `ARCX` for `US`).
2. **The risk-free rate is zero for now.** This matches the simulator, where cash earns nothing, and applies the same rule to the strategy and the benchmark. A real rate comes in one change with interest on cash in the simulator.

## Implementation choices made in PR 16, for review there

- **Conventions.** Daily returns close to close. Years are calendar time over 365.25 days. Daily figures are annualised with 252 sessions. Volatility is the sample standard deviation. Sortino's downside deviation is the root mean square of the returns below zero over every day. Maximum drawdown is measured close to close, with when it peaked, bottomed and recovered. The definitions are written once, in the docstring of `tyche.core.backtest.metrics`.
- **Decimal arithmetic in a fixed context**, so the same inputs give the same digits on every machine and a golden file can be compared exactly.
- **The benchmark starts at the first close, the strategy at the next open.** Both start from the same equity at the same moment. The strategy's first decision is at that close and fills at the next open, which is part of its execution and stays in its result.
- **Gaps in the benchmark's data.** A session with no bar repeats the last value; a distribution whose ex-date has no bar is reinvested at the next bar. A benchmark with no bar at or before the first close stops the run before it starts.
- **The benchmark need not be a candidate.** The runner loads it through the same data provider over the same days (from the cache only, for a backtest), or reuses the candidate's history when it is one. Its data is listed in `run.json`.
- **Trades for the win rate run from flat to flat per instrument, across all sleeves**, because fills are per account. A trade's profit is the cash of its fills, commissions included; distributions received while it was open are not counted. Positions open at the end are counted, not judged.
- **Turnover counts both sides**: the value of every fill over the average equity, per year. Buy-and-hold on SPY from 2005 to 2023 shows 0.03 a year.
- **No pass or fail verdict.** The metrics show each figure beside the benchmark's and the difference. Deciding that a strategy "beats the benchmark" needs the trial count, out-of-sample results and a deflated Sharpe ratio (PRs 20 and 21, then the Phase 3 gate). One backtest's difference is not that.
- **Where it goes.** `metrics.json` in the run's record folder, with the conventions it used; a `benchmark_equity` column in `equity.csv`; the benchmark and its data in `run.json`; and a summary table from `tyche backtest`. If a run cannot be measured (for example it halted before its first close), it is still recorded, `run.json` says why, and there is no `metrics.json`.
- **A golden-file regression test** runs a fixed backtest (two sleeves, quarterly dividends, trades that open and close) through `metrics.json`'s serialiser and compares every figure with a committed file. Regenerating it is a deliberate step, and its diff is reviewed number by number.

## Checked on real data

SPY from 2005-01-03 to 2023-12-29, Yahoo data in a scratch workspace:

| | Tyche's buy-and-hold | SPY total return (the benchmark) |
|---|---|---|
| CAGR | 9.09% | 9.59% |
| Volatility | 18.28% | 19.31% |
| Sharpe (rf 0) | 0.57 | 0.57 |
| Max drawdown | 53.23% | 55.20% |
| Exposure | 94.25% | 100% |

The benchmark grows 5.6875 times. Yahoo's own dividend-adjusted close grows 5.6839 times over the same dates; the 0.06% difference is the reinvestment convention (Yahoo scales earlier prices by the previous close, we reinvest at the ex-date close). The half point of CAGR between the two columns is what Tyche's costs and cash drag cost buy-and-hold.

## Alternatives considered

- **The simulated buy-and-hold as the benchmark.** Like for like on costs, but it flatters every strategy by the cash drag, and every comparison needs a second backtest and a second record.
- **Both, with the verdict on total return.** More output, and still a second run.
- **A constant risk-free rate in the config.** Wrong for most of 2005 to 2023 whatever value is picked, and inconsistent with cash earning 0% in the simulator.
- **A historical T-bill series (for example from FRED).** The most correct, but a new data source, adapter and fetch command, and still inconsistent until the simulator pays interest.
- **Annualising by the run's own sessions per year.** Slightly more exact, but different from the convention most tools use, which matters for the reference validation (PR 17).
- **`float` arithmetic.** Fine for statistics, but its last digits can differ between platforms, which makes a golden file brittle.

## Consequences

- A strategy must beat what holding the index actually paid, not Tyche's own imperfect copy of it. Tyche's buy-and-hold itself trails the benchmark, by about half a point of CAGR on SPY.
- Every workspace needs a `[benchmark]` table in `config/markets/US.toml`, and the benchmark's history must be fetched like a candidate's.
- Sharpe and Sortino over a zero rate read higher than published figures over T-bills, for the strategy and the benchmark alike. Comparisons between them stay fair; comparisons with outside numbers do not.
- PR 19's report reads `metrics.json` and `equity.csv` for its tables and charts.

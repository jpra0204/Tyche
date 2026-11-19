# Measuring against a benchmark

## What problem does this solve

"+421% over 19 years" sounds good until you learn that simply holding SPY paid more. A return on its own says nothing about skill. The question that matters is: **did this strategy do better than the simplest thing you could have done instead, after costs, for the risk it took?** That simplest thing is the benchmark.

There are two easy ways to get the comparison wrong:

1. **A benchmark that is too easy.** If the benchmark pays costs and leaves cash idle that a real investor would not, every strategy looks better than it is.
2. **Figures measured differently.** A Sharpe ratio over 0% next to one over T-bill rates, or a CAGR over trading days next to one over calendar years, compares nothing.

## The idea

- **Use total return.** An index ETF pays dividends. Holding it means receiving them and, for a fair bar, reinvesting them. A price-only benchmark is too easy by the dividends: on SPY from 2005 to 2023, 7.5% a year on price alone against 9.6% with dividends reinvested (measured on the cached Yahoo data). One that holds dividends as cash is too easy by the cash drag.
- **Same start, same days, same rules.** The benchmark starts from the same equity at the same moment as the strategy and is measured on exactly the same session closes, with the same formulas.
- **Show the difference, not a verdict.** One backtest beating the benchmark can be luck, especially after many tries. The metrics show each figure beside the benchmark's; deciding whether the strategy has an edge needs out-of-sample results and an overfitting correction.

The usual figures and what each catches:

| Figure | Catches |
|---|---|
| CAGR | Growth per year, so runs of different length compare |
| Volatility | How bumpy the ride was |
| Sharpe | Return per unit of all volatility |
| Sortino | Return per unit of downside only: rises are not punished |
| Maximum drawdown | The worst fall from a peak: what you would have had to sit through |
| Exposure | How much of the time money was actually at risk |
| Turnover | How much was traded, and so how much costs matter |
| Win rate | How often a closed trade made money. Meaningless alone: a strategy can win 90% of the time and still lose money |

## Where is it in Tyche

- `tyche.core.backtest.metrics` defines every figure once, in its module docstring, and computes them in `Decimal` ([ADR-0025](../adr/0025-metrics-against-the-benchmarks-total-return.md)).
- `benchmark_points` turns the benchmark's cached bars and distributions into an equity curve with every distribution reinvested at its ex-date close, no costs, no cash.
- The benchmark ETF is the `[benchmark]` table of the market profile. `tyche backtest` prints the table, and the record has `metrics.json` and a `benchmark_equity` column in `equity.csv`.

## What does it cost

- **A harder bar.** Even Tyche's own buy-and-hold trails it, by about half a point of CAGR on SPY over 2005 to 2023, because of commissions and cash. That is the truth about trading through Tyche, not a flaw in the measurement.
- **A simplification for now.** The risk-free rate is zero, matching the simulator's cash, which earns nothing. Ratios therefore read higher than published ones over T-bills, for strategy and benchmark alike.
- **Annualising short runs exaggerates.** A CAGR from a few months is a figure, not a forecast.

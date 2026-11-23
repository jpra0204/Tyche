# Running a backtest

A backtest replays history through exactly the code that will later trade on paper and live: the universe, your strategies, portfolio construction, the risk gate, execution and a simulated broker with IBKR's costs and settlement rules. It runs from your workspace's cache, never from the internet, and leaves a record of what ran.

You need a workspace with fetched data: see [Installation and your workspace](01-installation.md) and [Fetching market data](02-fetching-market-data.md).

## The holdout: history you cannot backtest

History from **2024-01-01** on is the **holdout**. No backtest may reach it. It is kept untouched for one purpose: the final check before a strategy is promoted (Phase 3). If you tune a strategy on the same history you then judge it on, it will look better than it is; a holdout that no experiment has seen is the honest test ([ADR-0024](../adr/0024-backtest-runner-holdout-and-run-record.md), learning note: [the holdout and the run record](../learning/holdout-and-run-records.md)).

The date is in `config/tyche.toml`:

```toml
[backtest]
holdout_starts = 2024-01-01
starting_cash = "10000"
```

It is a fixed date, so the holdout grows as time passes. **Never move it later**: history a backtest has seen cannot become a holdout again. `starting_cash` is the cash every backtest starts with, in USD for the `US` profile. Minimum commissions weigh more on a small account, so set it to what you would really trade with.

## Choose the instruments

A backtest replays the instruments listed in `config/markets/US.toml`, under `[universe]`:

```toml
instruments = [
    { symbol = "SPY", exchange = "ARCX", asset_class = "etf" }, # US large caps (S&P 500)
    { symbol = "QQQ", exchange = "XNAS", asset_class = "etf" }, # US large caps (Nasdaq-100)
    # ... IWM, EFA, EEM, TLT, IEF, GLD and VNQ: nine ETFs in all
]
```

These are the **candidates**. At every decision the universe rules in the same table decide which of them are eligible (price, liquidity, data quality), and only eligible ones are offered to your strategies. A strategy can only trade an instrument listed here: one that names an unlisted instrument never trades.

The template lists nine ETFs across US large and small caps, other developed and emerging markets, Treasuries, gold and real estate: what the example trend rotation chooses from. **Every backtest replays every candidate**, so each one must be fetched, even when your strategies trade only SPY. To backtest fewer, remove the others from the list.

## The benchmark

Every backtest is measured against the **benchmark**, named in the same file:

```toml
[benchmark]
symbol = "SPY"
exchange = "ARCX"
asset_class = "etf"
```

The benchmark is not a strategy that trades. It is what simply holding SPY paid over the same days: the backtest's starting equity buys SPY at the first close, and every dividend is reinvested at the close of its ex-date, with no commissions and no idle cash ([ADR-0025](../adr/0025-metrics-against-the-benchmarks-total-return.md)). It is a harder bar than Tyche's own buy-and-hold strategy, and the right one: it is what you would get without Tyche. It need not be one of the candidates, but its history must be fetched like theirs.

## Fetch the history first

A backtest reads only what is already cached. It also needs some history **before** its first day, to warm up: the universe's liquidity average needs 20 sessions, and each strategy needs its own lookback (200 sessions, about ten months, for the example strategies). Fetch from a year before you plan to start. The nine candidates are listed on two exchanges, so two commands fetch them all:

```bash
uv run tyche data fetch SPY IWM EFA EEM GLD VNQ --exchange ARCX --from 2004-01-01 --to 2023-12-29
```

```bash
uv run tyche data fetch QQQ TLT IEF --exchange XNAS --from 2004-01-01 --to 2023-12-29
```

GLD and VNQ started trading in late 2004, so `tyche data fetch` reports the sessions before that as missing. That is expected: until a fund has enough history it is "warming up", and strategies are not offered it.

If something is missing, the backtest stops and prints the exact command to run:

```text
Error: SPY@ARCX: sessions from 2004-12-03 to 2004-12-31 are not in the cache yet. Fetch it first:
  tyche data fetch SPY --exchange ARCX --from 2004-12-03 --to 2004-12-31
```

## Run

```bash
uv run tyche backtest --from 2005-01-03
```

| Option | Meaning |
|---|---|
| `--from` | First day to trade, `YYYY-MM-DD`. Required. History before it is used only to warm up. |
| `--to` | Last day to trade. Defaults to the day before the holdout. A date in the holdout is refused. |
| `--risk-profile` | The risk profile the risk gate applies, a file in `config/risk/`. Defaults to `default`. See [risk profiles](08-risk-profiles.md#what-a-profile-does-to-a-backtest). |
| `--home` | Workspace folder, as for every command. |

```text
Backtest 20261123T145931Z-239f4f5d: completed
  Range:         2005-01-03 to 2023-12-31, 4,781 sessions
  Warm-up:       20 sessions from 2004-12-03 (20 needed)
  Starting cash: 10000 USD
  Final equity:  14567.81 USD (+45.68%)
  Fills:         98; free-riding violations: 0
  Risk profile:  default; the risk gate shrank 4,781 contributions and blocked 0 entries
  Account rules: daily loss limit hit after 0 sessions; drawdown kill never hit
  Metrics           strategy  SPY@ARCX total return
    CAGR               2.00%       9.59%
    Volatility         3.69%      19.31%
    Sharpe (rf 0)       0.56        0.57
    Sortino (rf 0)      0.78        0.80
    Max drawdown      13.19%      55.20%
    Exposure          19.34%     100.00%
  Turnover:      0.15 a year; costs 99.00 USD
  Trades:        0 closed, win rate n/a; 1 still open
  Code:          0.1.0+g0123456789ab
  Record:        /Users/<you>/tyche-workspace/reports/backtests/20261123T145931Z-239f4f5d/run.json
  Report:        /Users/<you>/tyche-workspace/reports/backtests/20261123T145931Z-239f4f5d/report.html
```

- **Range** is what was traded; **Warm-up** is the history learned before it. If fewer warm-up sessions were available than needed, the first decisions wait for enough history.
- **Final equity** is cash plus holdings at the last close. The change is total, not yearly.
- **Metrics** put your strategies, all together, beside the benchmark. Both start from the same equity at the same first close and are measured on the same closes with the same formulas, defined below.
- **Turnover, costs and trades** are about your strategies only: the benchmark pays nothing and never trades. **Costs** here are commissions and regulatory fees; slippage is in the prices, and the report's cost-drag section counts it too.
- **Risk profile** names the profile the risk gate applied, and how often it cut what a strategy asked for. Here buy-and-hold asks for all of its budget in SPY at every close and `default` caps a position at 20%, so it holds a fifth of the account: that is why its return is far below the benchmark's while its Sharpe ratio is about the same. Without limits the same run ends at 52,168 USD ([risk profiles](08-risk-profiles.md#expect-smaller-numbers-under-default)).
- **Account rules** says how many sessions ended with a loss at or beyond the profile's daily loss limit (no entry or addition at those closes), and whether the drawdown kill halted trading. A halted run still goes to its last day, but sends no order after the halt; read anything after that date as "what if nobody restarted it" ([risk profiles](08-risk-profiles.md#what-a-profile-does-to-a-backtest)).
- **Fills** counts every trade. **Free-riding violations** should always be 0 ([costs and settlement](../developer-guide/ibkr-canada-costs-and-settlement.md)).
- **Code** is Tyche's version and the git commit it ran from. If the code had uncommitted changes, it ends in `.dirty` and a warning says the commit alone cannot reproduce the run.

A run of 19 years over the nine candidates takes about 20 seconds.

## The metrics

| Figure | Meaning |
|---|---|
| CAGR | Growth per year, compounded, over calendar years. Over a run of a few months it is a figure, not a forecast |
| Volatility | How much the daily returns vary (their standard deviation), scaled to a year with 252 sessions |
| Sharpe (rf 0) | Average daily return over its volatility, scaled to a year. Above the benchmark's means more return for the ups and downs taken |
| Sortino (rf 0) | Like Sharpe, but only the falls count as risk |
| Max drawdown | The largest fall from a peak close to a later close. `metrics.json` adds when it peaked, bottomed and recovered |
| Exposure | The average share of equity invested; the rest was cash |
| Turnover | The value of everything bought and sold, per year, as a multiple of the average equity |
| Trades | A trade runs from the purchase that opens a position to the sale that closes it. The win rate is the share of closed trades that made money after commissions; dividends received are not counted in it |

*rf 0* means the ratios are measured over a risk-free rate of zero, because cash earns nothing in the simulator. They read higher than ratios published over Treasury bill rates, for your strategy and the benchmark alike, so compare them with each other, not with outside figures.

A figure that cannot be computed (a Sharpe ratio for a run with no ups and downs, a win rate with no closed trade) shows as `n/a`.

**These numbers are not a verdict.** A strategy that shows a higher CAGR or Sharpe than the benchmark on one backtest has not proven an edge: it may be luck, or the result of trying many versions. Out-of-sample testing ([walk-forward](04-walk-forward.md)) and a trial count with a deflated Sharpe ratio ([parameter sweeps](05-parameter-sweeps.md)) come before any such claim.

## The record

Every run writes a folder under `reports/backtests/` in your workspace, named after the run:

| File | Holds |
|---|---|
| `run.json` | What ran: the code version, the config hash and every setting behind it, the range and warm-up, the holdout, the starting cash, the rebalance band and price buffer, each strategy with its version and budget, the data used (when it was fetched, how many bars, any data issues) and the outcome |
| `equity.csv` | Your account at every session close: equity, cash, settled cash and the value of holdings; and the benchmark's equity at the same close |
| `fills.csv` | Every fill: date, instrument, side, shares, price after slippage, commission and fees, settlement date |
| `metrics.json` | The metrics of your strategies and of the benchmark, the differences, and the conventions used (sessions per year, the risk-free rate). Fractions are written as decimals: `"0.090912"` is 9.09% |
| `report.html` | The report: open it in any browser. Built from the four files above alone, so it can always be rebuilt |

Records are part of your workspace's private git repository: commit them with the configuration that produced them. Every run is recorded, including one that halts, because later phases count how many experiments were tried before a result was found.

## The report

Every measured run gets `report.html` in its record folder: one file, about 300 to 400 KB, that opens in any browser with no internet connection ([ADR-0028](../adr/0028-backtest-report-html-and-cost-drag.md)). It has six sections:

| Section | Shows |
|---|---|
| Summary | The metrics beside the benchmark's, with when each worst fall happened; charts of equity (on a logarithmic scale) and of drawdown |
| Year by year | Each calendar year's return, yours and the benchmark's |
| Trading | Fills, closed trades, win rate, turnover, free riding; a chart of how much of the account was invested |
| Cost drag | What costs took: commissions and fees, slippage, their share of the profit, and the CAGR before and after costs, with a chart of both curves |
| What ran | The code, the config hash, the costs and execution rules, each strategy with its version and budget |
| Data and its limits | Every instrument's history (bars, dates, data issues, dividends, splits) and the limits every result shares |

**The cost drag** adds every cost paid back onto the equity at each close, which gives the run before costs, and measures both the same way. Slippage is worked back from each fill's price. Money not spent on costs would have grown too, so the drag shown is a floor. On a small account it is often the largest number in the report: on 2005 to 2023 with USD 10,000, the example mean reversion's costs were 48% of its profit before costs, and slippage alone was more than twice its commissions.

To rebuild a report, for a run recorded before reports existed or after Tyche's report changes:

```bash
uv run tyche report 20261119T172646Z-75505646
```

It reads only the record folder, never the cache, and replaces `report.html`. The same record always gives the same file.

## Reading a buy-and-hold run

With the template's buy-and-hold on SPY:

- It buys at the first open with about 98% of the cash: the rest is the price buffer for the open being higher than the close ([installation, section 4](01-installation.md#4-check-the-configuration)).
- Dividends arrive as cash and stay as cash until the holding is more than 10% below its target (the rebalance band); then it buys more. Over 2005 to 2023 that happens twice, and the run ends with about 9% in cash.
- So it trails the benchmark: 9.09% a year against 9.59% for SPY with every dividend reinvested. That half point is what commissions and idle cash cost buy-and-hold through Tyche. Its drawdown is a little smaller for the same reason: the cash did not fall.

## Trying the example strategies

Two example strategies come with the workspace, in `config/strategies/`, without a budget, so they do not run until you give them one ([ADR-0027](../adr/0027-example-strategies-fixed-in-advance.md)). They exist to exercise Tyche, not to make money, and their parameters were fixed before any backtest ran.

| Strategy | What it does |
|---|---|
| `trend_rotation` | Once a month, holds the three of the nine ETFs that rose most over about six months, a third of its budget each, but only those above their 200-session average; the rest stays in cash |
| `mean_reversion` | On SPY and QQQ, buys a sharp two-day dip (RSI(2) below 10) while the price is above its 200-session average, with a stop 2.5 average true ranges below, and sells when the close rises above its 5-session average |

To run one alone, change the budgets in `config/tyche.toml`:

```toml
[strategies]
trend_rotation = "1.0"
```

or split the account between several, with budgets adding up to at most 1. Each one's file says what its parameters mean. **Changing a parameter after seeing a result, then testing again, is how a backtest gets fitted to the past**: every such run is a new trial, and later phases count them.

On 2005 to 2023 real data, USD 10,000, each strategy alone:

| | Trend rotation | Mean reversion | SPY total return |
|---|---|---|---|
| CAGR | 5.97% | 1.28% | 9.59% |
| Volatility | 13.70% | 5.25% | 19.31% |
| Max drawdown | 29.68% | 12.44% | 55.20% |
| Exposure | 86% | 10% | 100% |
| Trades | 175 closed | 328 closed, 41 by the stop | |
| Costs | USD 544 | USD 698 | none |

Neither beats holding SPY. The rotation's worst fall was 29.7% (2018 to 2020) against SPY's 55.2% (2007 to 2009), and it paid for that with a lower return. The mean reversion is invested a tenth of the time, so its low return and low drawdown both come mostly from sitting in cash. One backtest is not a verdict either way.

## Troubleshooting

| Message | What to do |
|---|---|
| `… is the reserved holdout; end the backtest before 2024-01-01` | Give an earlier `--to`, or leave it out to stop the day before the holdout. |
| `… are not in the cache yet. Fetch it first:` | Run the command printed below the message, then the backtest again. |
| `config/tyche.toml: … backtest: Field required` | Your workspace was created before PR 15. Copy the `[backtest]` table, with its comments, from the `config/tyche.toml` of a new workspace (`uv run tyche init --home <scratch-folder>`) into yours. |
| `config/markets/US.toml: … benchmark: Field required` | Your workspace was created before PR 16. Copy the `[benchmark]` table, with its comments, from the `config/markets/US.toml` of a new workspace (`uv run tyche init --home <scratch-folder>`) into yours. |
| `IWM@ARCX: sessions from … are not in the cache yet` | The template's candidates grew from two to nine in PR 18. Fetch them (see [Fetch the history first](#fetch-the-history-first)), or remove the ones you do not want from `instruments` in `config/markets/US.toml`. |
| `… gives strategy 'trend_rotation' a budget, but config/strategies/trend_rotation.toml does not exist` (or `mean_reversion`) | Your workspace was created before PR 18. Copy the file from a new workspace (`uv run tyche init --home <scratch-folder>`) into your `config/strategies/`. |
| `no bar of the benchmark SPY@ARCX on or before …` | Fetch the benchmark's history from before your first day, as for a candidate. |
| `Metrics:       not measured: …` | The run could not be measured, for example because it halted before its first close. The record is written without `metrics.json` and without a report; the message says why. |
| `Error: no backtest, walk-forward, sweep or capital record named …` | `tyche report` takes the run id exactly as `tyche backtest` printed it: the record folder's name under `reports/backtests/`. |
| `… run.json is record format …` | The record was written by a different version of Tyche than the one reading it. |
| `config/markets/US.toml: … universe.instruments: Field required` | Your workspace was created before PR 15. Copy the `instruments` list, with its comments, into the `[universe]` table of your `config/markets/US.toml`. |
| `Error: the run halted: …` | A stage found something it cannot handle and stopped the run rather than guess (fail closed). The record is still written. The message names the problem; please share it, since it usually means a bug. |

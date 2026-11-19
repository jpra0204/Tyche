# Running a backtest

A backtest replays history through exactly the code that will later trade on paper and live: the universe, your strategies, portfolio construction, the risk gate, execution and a simulated broker with IBKR's costs and settlement rules. It runs from your workspace's cache, never from the internet, and leaves a record of what ran.

You need a workspace with fetched data: see [Installation and your workspace](01-installation.md) and [Fetching market data](02-fetching-market-data.md).

*Metrics (PR 16) and the report with charts (PR 19) come next. For now a backtest prints the final equity and writes the equity curve and the fills to files.*

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
    { symbol = "SPY", exchange = "ARCX", asset_class = "etf" },
    { symbol = "QQQ", exchange = "XNAS", asset_class = "etf" },
]
```

These are the **candidates**. At every decision the universe rules in the same table decide which of them are eligible (price, liquidity, data quality), and only eligible ones are offered to your strategies. A strategy can only trade an instrument listed here: one that names an unlisted instrument never trades.

## Fetch the history first

A backtest reads only what is already cached. It also needs some history **before** its first day, to warm up: the universe's liquidity average needs 20 sessions, and each strategy needs its own lookback. Fetch from a month or two before you plan to start:

```bash
uv run tyche data fetch SPY --exchange ARCX --from 2004-11-01 --to 2023-12-29
```

```bash
uv run tyche data fetch QQQ --exchange XNAS --from 2004-11-01 --to 2023-12-29
```

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
| `--home` | Workspace folder, as for every command. |

```text
Backtest 20261119T172646Z-75505646: completed
  Range:         2005-01-03 to 2023-12-31, 4,781 sessions
  Warm-up:       20 sessions from 2004-12-03 (20 needed)
  Starting cash: 10000 USD
  Final equity:  52168.20 USD (+421.68%)
  Fills:         3; free-riding violations: 0
  Code:          0.0.1+g4ed905d3be34
  Record:        /Users/<you>/tyche-workspace/reports/backtests/20261119T172646Z-75505646/run.json
```

- **Range** is what was traded; **Warm-up** is the history learned before it. If fewer warm-up sessions were available than needed, the first decisions wait for enough history.
- **Final equity** is cash plus holdings at the last close. The change is total, not yearly; yearly figures and the comparison with the benchmark come with the metrics (PR 16).
- **Fills** counts every trade. **Free-riding violations** should always be 0 ([costs and settlement](../developer-guide/ibkr-canada-costs-and-settlement.md)).
- **Code** is Tyche's version and the git commit it ran from. If the code had uncommitted changes, it ends in `.dirty` and a warning says the commit alone cannot reproduce the run.

A run of 19 years with two instruments takes a few seconds.

## The record

Every run writes a folder under `reports/backtests/` in your workspace, named after the run:

| File | Holds |
|---|---|
| `run.json` | What ran: the code version, the config hash and every setting behind it, the range and warm-up, the holdout, the starting cash, the rebalance band and price buffer, each strategy with its version and budget, the data used (when it was fetched, how many bars, any data issues) and the outcome |
| `equity.csv` | Your account at every session close: equity, cash, settled cash and the value of holdings |
| `fills.csv` | Every fill: date, instrument, side, shares, price after slippage, commission and fees, settlement date |

Records are part of your workspace's private git repository: commit them with the configuration that produced them. Every run is recorded, including one that halts, because later phases count how many experiments were tried before a result was found.

## Reading a buy-and-hold run

With the template's buy-and-hold on SPY:

- It buys at the first open with about 98% of the cash: the rest is the price buffer for the open being higher than the close ([installation, section 4](01-installation.md#4-check-the-configuration)).
- Dividends arrive as cash and stay as cash until the holding is more than 10% below its target (the rebalance band); then it buys more. Over 2005 to 2023 that happens twice, and the run ends with about 9% in cash. This cash drag makes buy-and-hold look a little worse than SPY's published total return, which reinvests every dividend. Keep it in mind when the metrics compare a strategy with it.

## Troubleshooting

| Message | What to do |
|---|---|
| `… is the reserved holdout; end the backtest before 2024-01-01` | Give an earlier `--to`, or leave it out to stop the day before the holdout. |
| `… are not in the cache yet. Fetch it first:` | Run the command printed below the message, then the backtest again. |
| `config/tyche.toml: … backtest: Field required` | Your workspace was created before PR 15. Copy the `[backtest]` table, with its comments, from the `config/tyche.toml` of a new workspace (`uv run tyche init --home <scratch-folder>`) into yours. |
| `config/markets/US.toml: … universe.instruments: Field required` | Your workspace was created before PR 15. Copy the `instruments` list, with its comments, into the `[universe]` table of your `config/markets/US.toml`. |
| `Error: the run halted: …` | A stage found something it cannot handle and stopped the run rather than guess (fail closed). The record is still written. The message names the problem; please share it, since it usually means a bug. |

# Parameter sweeps

A sweep tries a strategy with every combination of a few parameter values, each a backtest over the same days, and picks the combination with the highest Sharpe ratio. It then tells you how far to trust that pick. The best of many tries looks better than it is, even when none of them has an edge, so the pick comes with a **deflated Sharpe ratio**: the chance that its true Sharpe ratio is above zero, once every try behind it is counted.

Read this before your first sweep: **every combination you run is counted for good.** The next sweep of the same strategy is judged against all of them. A sweep is not free exploration; it spends something you cannot get back. The learning note [multiple testing and the deflated Sharpe ratio](../learning/multiple-testing.md) explains why.

Everything on the [backtest page](03-running-a-backtest.md) applies: the holdout, the candidates, the benchmark, fetching history first.

## Write a sweep

A sweep is a file in `config/sweeps/`. New workspaces ship one, `config/sweeps/trend_rotation.toml`:

```toml
strategy = "trend_rotation"

[grid]
holdings = [2, 3, 4]
momentum_sessions = [63, 126, 252]
trend_sessions = [150, 200, 250]
```

- `strategy` is a configured strategy: it needs a budget under `[strategies]` in `config/tyche.toml`. The example strategies ship without one, so to run this sweep give `trend_rotation` a budget first. The other configured strategies run alongside, unchanged.
- `[grid]` lists each parameter to vary and its values, in the order you want them tried. Parameters you do not list keep the values in `config/strategies/<strategy>.toml`. Decimals are strings, as in the strategy file.
- The grid holds every combination: here 3 × 3 × 3 = 27.

Every combination is built before anything runs, so a typo or a value the strategy refuses stops the sweep at once with the file and the parameter named.

Plan the grid from reasons you can state (a holding period you believe in, a range the literature uses), not from results you have seen. Widening a grid after seeing that the best value sat at its edge is the overfitting the trial count exists to catch.

## Run

```bash
uv run tyche sweep trend_rotation --from 2005-01-03
```

| Option | Default | Meaning |
|---|---|---|
| `NAME` | (required) | The sweep's file name in `config/sweeps/`, without `.toml` |
| `--from` | (required) | First session date to trade, for every trial |
| `--to` | the day before the holdout | Last session date to trade |
| `--risk-profile` | `default` | The risk profile every trial runs under, a file in `config/risk/`. Compare trials only under one profile | The figures on this page were recorded before the risk gate applied limits (Phase 2, PR 2); under `default` they are smaller ([risk profiles](08-risk-profiles.md#expect-smaller-numbers-under-default)). |

It prints the trial count first, then a line per trial, then the pick:

```text
Sweep trend_rotation: 27 combinations of trend_rotation (trend_rotation); 27 trials counted with the 1 already recorded
  Trial   7/27  holdings=2 momentum_sessions=252 trend_sessions=150  Sharpe   0.41  CAGR    5.01%
  Trial   1/27  holdings=2 momentum_sessions=63 trend_sessions=150  Sharpe   0.65  CAGR    9.07%
  ...
  Trial  27/27  holdings=4 momentum_sessions=252 trend_sessions=250  Sharpe   0.69  CAGR    8.18%
Sweep 20261122T224025Z-c05df771: 27 trials, 27 measured
  Pick:          trial 26, holdings=4 momentum_sessions=252 trend_sessions=200 (in-sample)
  Metrics           strategy  SPY@ARCX total return
    CAGR               8.28%       9.59%
    Volatility        12.19%      19.31%
    Sharpe (rf 0)       0.71        0.57
    Sortino (rf 0)      1.00        0.80
    Max drawdown      19.54%      55.20%
    Exposure          83.45%     100.00%
  Turnover:      3.58 a year; costs 421.51 USD
  Trades:        136 closed, win rate 52.21%; 4 still open
  Deflated Sharpe ratio: 98.2% after 27 trials (significant at 95%)
Warning: The pick's holdings is the last value of the grid (4): the best value may lie beyond it, and widening the grid adds trials.
Warning: The pick's momentum_sessions is the last value of the grid (252): the best value may lie beyond it, and widening the grid adds trials.
  Code:          0.0.1+g...
  Record:        /Users/<you>/tyche-workspace/reports/sweeps/20261122T224025Z-c05df771
  Report:        /Users/<you>/tyche-workspace/reports/sweeps/20261122T224025Z-c05df771/report.html
```

That is the example sweep over 2005 to 2023, run in a scratch workspace with the trend rotation alone. It took about 16 minutes.

The combination that needs the most history runs first, so that history missing from the cache stops the sweep straight away rather than after many trials.

## What the numbers mean

**The pick is in-sample.** It was chosen on the same days it is measured on, so its figures are the best of these trials over this history, not a forecast. For an out-of-sample result, run the sweep [inside a walk-forward](#inside-a-walk-forward).

**The deflated Sharpe ratio** is a probability. 95% or more means the pick is unlikely to be the luck of the best of that many tries. Below 95%, it is not distinguishable from luck.

**A significant pick has not been shown to beat the benchmark.** The question the deflated Sharpe ratio answers is "is the true Sharpe ratio above zero?", which is a low bar over many years. In the example above the pick scores 98.2%, but simply holding SPY over the same days scores 99.3% on the same test. And the pick's CAGR trails SPY's by 1.3 points a year. Its higher Sharpe ratio was found in-sample, with two of its three parameters at the edge of the grid. Read the deflated Sharpe ratio as a filter that throws out luck, never as a verdict that a strategy is worth trading. The walk-forward is the better test.

**The trial count** behind it is every distinct version of the strategy's plugin recorded in your workspace: each backtest, each walk-forward window and each sweep combination, with each distinct set of parameters counted once. Rerunning exactly the same parameters adds nothing; changing one adds a trial. The terminal line `27 trials counted with the 1 already recorded` means the count includes one version recorded before this sweep (here, the configured rotation, which is also in the grid).

**Warnings** follow, one sentence each:

| Warning | Means |
|---|---|
| Below 95% | The pick may be luck |
| The pick's value is the first or last of the grid | The best value may lie beyond the grid. Widening it is a new search and adds trials |
| An isolated peak | Its neighbours on the grid (one step of one parameter away) do much worse: a small change loses most of the result |
| Trials halted or could not be measured | They count as trials but tell nothing about the spread of results |

## The record

Every sweep writes a folder under `reports/sweeps/`:

| File | Holds |
|---|---|
| `sweep.json` | What ran: the code version, the config hash and every setting, the sweep file and its hash, the range, how it ended |
| `trials.json` | Every trial's parameters, its trial key and its results; the pick; the trial count; the deflated Sharpe ratio with every input; the warnings |
| `pick/` | The pick's full backtest record: `run.json`, `metrics.json`, `equity.csv`, `fills.csv` |
| `report.html` | The report, built from this folder alone |

Only the pick keeps its equity and fills. Any other trial can be rerun as an ordinary backtest by putting its parameters in the strategy file; it is already counted, so that adds no trial. Commit the folder with your workspace: **do not delete records to lower the trial count.** The count is only honest if every trial stays recorded.

## The report

`report.html` opens with what to keep in mind (the pick is in-sample, the verdict, the warnings), then:

| Section | Shows |
|---|---|
| How much to trust the pick | The deflated Sharpe ratio and every input: the trials counted, the variance of their Sharpe ratios, the number of daily returns, the skewness and kurtosis |
| The pick | Its parameters, its figures beside the benchmark's, and charts of equity and drawdown |
| Every trial | Each combination's Sharpe ratio, CAGR, drawdown and trades, in the grid's order |
| What ran | The code, the config hash, the sweep file and the values tried |
| Data and its limits | The limits every backtest shares, and four a sweep adds |

`tyche report <id>` rebuilds it.

## Inside a walk-forward

```bash
uv run tyche walk-forward --from 2005-01-03 --sweep trend_rotation
```

Each fold runs every combination on its training window, and its test window runs the one with the highest Sharpe ratio there, on a year the pick has not seen. The test windows joined are then an honest out-of-sample record of the process "sweep the past, trade the pick next year". Each training window's folder keeps its pick's full record and its own `trials.json`; the report adds a table of what each training window picked and its deflated Sharpe ratio.

A pick that changes from fold to fold is a sign that the differences between combinations are noise. A large, steady gap between in-sample and out-of-sample results is the sign of overfitting.

Each combination counts as one trial, however many folds run it. The out-of-sample result is not deflated, because nothing was chosen on it. But running several walk-forwards with different grids or folds and keeping the best one is choosing again: the trial count is what shows it.

It is slow: every combination runs on every training window. With the defaults and the example grid, that is 27 times the training windows of a plain walk-forward: about two and a half hours on this profile.

What the example gave, testing 2010 to 2023:

| Out of sample | Sweep picks on each training window | Configured parameters, no sweep | SPY total return |
|---|---|---|---|
| CAGR | 4.29% | 4.57% | 12.58% |
| Sharpe (rf 0) | 0.42 | 0.42 | 0.77 |

The training windows picked seven different combinations over the 14 folds. Thirteen of the picks had a deflated Sharpe ratio above 95%. None of that carried into the test years: choosing the parameters each year did no better than fixing them in advance. That is what a passing deflated Sharpe ratio on a training window can look like. Judge a strategy by the walk-forward's out-of-sample result, not by the sweep's pick.

## Troubleshooting

| Message | What to do |
|---|---|
| `… has no budget under [strategies] in config/tyche.toml` | Give the strategy a budget, lowering the others so the total stays at most 1 |
| `config/sweeps/<name>.toml: … invalid parameter(s)` | A value in the grid is not a parameter of the plugin, has the wrong type, or is refused by the strategy. The message names it |
| `… are not in the cache yet. Fetch it first:` | The combination with the longest lookback needs history before what you fetched. Run the printed command, then the sweep again |
| `missing_session` data issues for sessions before an ETF existed (GLD before November 2004, VNQ before September 2004) | Expected. Yahoo has no bars before a fund's first day. Running the printed fetch command records that, so the sweep no longer stops there, and every run lists those sessions as missing. A strategy simply has no price for that ETF on those days |
| `cannot read it to count trials` | A record under `reports/` is damaged. Trials cannot be counted honestly without it: restore it from your workspace's git history |

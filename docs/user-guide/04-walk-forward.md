# Walk-forward: in-sample and out-of-sample

A single backtest tells you how your strategies did over one stretch of history. A walk-forward asks a harder question: how they did on years that were not used to set them up. It cuts history into folds, each a **training window** (in-sample) followed by a **test window** (out-of-sample). It runs both as backtests, and reports the two side by side. The test windows, joined end to end, are the out-of-sample result.

Everything on the [backtest page](03-running-a-backtest.md) applies here: the holdout, the candidates, the benchmark, fetching history first. A walk-forward reads the same cache and never reaches the holdout.

## What "out-of-sample" means

**Without `--sweep`, the training window chooses nothing.** Each test window runs your strategies with the parameters in their files, exactly as configured. With `--sweep <name>`, each training window picks the parameters its test window runs (see [parameter sweeps](05-parameter-sweeps.md#inside-a-walk-forward)). Without a sweep:

- the in-sample and out-of-sample results are the same strategy, run over different years;
- a big gap between them shows that the strategy's results depend on the period, **not** that it was overfitted, because nothing was fitted;
- rules you chose after reading research on this same history are never fully out-of-sample on it. Only the holdout is history no experiment has used.

The report says this in its first lines. The learning note [walk-forward testing and overfitting](../learning/walk-forward-testing.md) explains the idea.

## Run

```bash
uv run tyche walk-forward --from 2005-01-03
```

| Option | Default | Meaning |
|---|---|---|
| `--from` | (required) | First day of the first training window |
| `--to` | the day before the holdout | Last day of the last test window |
| `--train-years` | 5 | Calendar years in the first training window |
| `--test-years` | 1 | Calendar years in each test window |
| `--rolling` | off | Keep every training window at `--train-years`, sliding forward, instead of growing it from `--from` |
| `--sweep` | none | A sweep in `config/sweeps/`: every combination runs on each training window, and the test window runs the one with the highest Sharpe ratio |
| `--risk-profile` | `default` | The risk profile every fold runs under, a file in `config/risk/` | The figures on this page were recorded before the risk gate applied limits (Phase 2, PR 2); under `default` they are smaller ([risk profiles](08-risk-profiles.md#expect-smaller-numbers-under-default)). |

Windows are whole calendar years. With the defaults and history from 2005, the first fold trains on 2005 to 2009 and tests 2010; the last trains on 2005 to 2022 and tests 2023: 14 folds. Each window is a backtest of its own, starting from your `starting_cash`, so a walk-forward takes much longer than one backtest. Over 2005 to 2023 on the nine-ETF profile it takes 2 to 3 minutes.

It prints a line as each window finishes, then the joined test windows beside the benchmark:

```text
Walk-forward, anchored: 5-year first training window, 1-year test windows
  Fold  1 train 2005-01-03 to 2009-12-31  CAGR   11.52%  benchmark    0.48%
  Fold  1 test  2010-01-01 to 2010-12-31  return   -2.65%  benchmark   13.14%
  ...
  Fold 14 train 2005-01-03 to 2022-12-31  CAGR    5.78%  benchmark    8.73%
  Fold 14 test  2023-01-01 to 2023-12-31  return    8.19%  benchmark   26.72%
Walk-forward 20261120T005537Z-c05df771: completed, 14 of 14 folds
  Out of sample: 2010-01-01 to 2023-12-31, the test windows joined
  Metrics           strategy  SPY@ARCX total return
    CAGR               4.57%      12.58%
    Volatility        12.33%      17.29%
    Sharpe (rf 0)       0.42        0.77
    Max drawdown      21.92%      33.70%
    Exposure          83.99%     100.00%
  Ahead of the benchmark in 2 of 14 test windows
  Code:          0.0.1+g...
  Record:        /Users/<you>/tyche-workspace/reports/walk_forward/20261120T005537Z-c05df771/walk_forward.json
  Report:        /Users/<you>/tyche-workspace/reports/walk_forward/20261120T005537Z-c05df771/report.html
```

That is the trend rotation alone. Training windows are compared by CAGR, because they differ in length; test windows by their return over the year.

## How the test windows are joined

Each test window starts in cash and is measured from its first close. To join them, each window's equity is scaled to start where the previous one ended, so the joined curve compounds the windows' returns. The benchmark, SPY's total return, is measured over each test window from the same starting cash and joined the same way. Three consequences:

- Each test window buys its positions again: a strategy that holds for years pays one entry per window, and holds nothing on the window's first session. Buy-and-hold trails the benchmark by a little more here than in a single backtest.
- Every window trades your starting cash, not what earlier windows grew to. The joined result compounds returns; it is not one account's history.
- The move from one window's last close to the next one's first close counts as no change, for your strategies and the benchmark alike.

## The record

Every walk-forward writes a folder under `reports/walk_forward/`, named like a backtest's:

| File | Holds |
|---|---|
| `walk_forward.json` | What ran: the code version, the config hash and every setting, the range, the scheme, the train step, each fold's windows and where their records are, and how it ended |
| `metrics.json` | The joined test windows and the joined benchmark, measured as a backtest's are, and how many test windows beat the benchmark |
| `equity.csv` | The joined equity, the amount invested and the joined benchmark at every test close, with the fold each close belongs to |
| `report.html` | The report, built from this folder alone |
| `folds/01-train/`, `folds/01-test/`, ... | Each window's full backtest record: `run.json`, `metrics.json`, `equity.csv` and `fills.csv` |

A walk-forward record is about 7 MB with the defaults, most of it the training windows' equity and fills. Commit it with your workspace like a backtest's record. With a sweep, each training window keeps only its pick's full record and a `trials.json` with every combination's results, so the size stays about the same.

## The report

`report.html` has five sections:

| Section | Shows |
|---|---|
| Out of sample | The joined test windows against the joined benchmark, how many test windows beat it, and charts of equity and drawdown |
| Fold by fold | For each fold, in-sample CAGR and out-of-sample return, each against the benchmark; then Sharpe ratios and drawdowns |
| Trading in the test windows | Fills, closed trades, win rate, exposure and commissions in each test window, and in total |
| What ran | The code, the config hash, the scheme, the train step, each strategy's budget, and where each window's record is |
| Data and its limits | The limits every backtest shares, and four a walk-forward adds |

To rebuild it:

```bash
uv run tyche report 20261120T005537Z-c05df771
```

`tyche report` takes a backtest's id, a walk-forward's or a sweep's.

## Reading the example strategies

On real data, USD 10,000, each strategy alone, testing 2010 to 2023:

| | Buy-and-hold | Trend rotation | Mean reversion | SPY total return |
|---|---|---|---|---|
| Out-of-sample CAGR | 12.14% | 4.57% | 1.25% | 12.58% |
| Sharpe (rf 0) | 0.78 | 0.42 | 0.25 | 0.77 |
| Max drawdown | 32.54% | 21.92% | 13.82% | 33.70% |
| Test years ahead of the benchmark | 4 of 14 | 2 of 14 | 3 of 14 | |

The rotation's fold table is the instructive part. On its first training window (2005 to 2009) it beat the benchmark by 11 points a year, mostly in 2007 and 2008. In 2008 it held Treasuries and gold and lost 4.5%, while SPY lost 36.8%. Each later fold dilutes 2008 with calmer years, and from fold 7 on even the training window trails the benchmark. A single 2005 to 2009 backtest would have suggested an edge that the next 14 years did not show.

## Troubleshooting

| Message | What to do |
|---|---|
| `… leaves no test window after a 5-year training window` | The range is too short for one training window and one test year. Start earlier, or give a smaller `--train-years`. |
| `Error: the walk-forward stopped: …` | A window halted or could not be measured. The windows before it are recorded, and `walk_forward.json` says which one stopped and why. |
| `… are not in the cache yet. Fetch it first:` | Run the command printed, then the walk-forward again. The windows already run stay recorded under the stopped walk-forward. |
| `Error: no backtest, walk-forward, sweep or capital record named …` | `tyche report` takes the id exactly as it was printed: a folder's name under `reports/backtests/`, `reports/walk_forward/`, `reports/sweeps/` or `reports/capital/`. |

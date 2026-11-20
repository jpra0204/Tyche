# ADR-0029: Walk-forward: anchored folds of calendar years, and a train step that keeps the configured parameters until sweeps exist

- **Status:** Accepted (Pablo, 2026-11-20)
- **Date:** 2026-11-20

## Context

Phase 1, PR 20 adds what the brief asks for in section 6: "train/test splits and walk-forward analysis. Report in-sample and out-of-sample results separately." The Phase 3 gate will rely on it too: every proposal is tried in a walk-forward against the current version.

A walk-forward cuts history into folds. Each fold has a training window and a test window right after it. Something is chosen on the training window, usually parameters, and is then tried on the test window, which the choice has not seen. Two questions came up before any code:

1. **What does the training window choose?** Choosing parameters needs a set of candidates and a rule to pick one, which is the parameter sweeps of PR 21. The example strategies' parameters were also fixed in advance and must not be tuned (ADR-0027).
2. **How do the windows move?** Anchored training windows all start at the beginning and grow. Rolling ones keep a fixed length and slide forward.

## Decision

1. **PR 20 builds the walk-forward, with a train step that keeps the configured parameters.** Each fold's training window and test window run as backtests, and their results are reported side by side. Between the two runs, a train step decides what the test window runs. For now it is `keep_configured` and chooses nothing. PR 21 replaces it with a choice made on the training window alone.

   Until then, the gap between in-sample and out-of-sample results shows how results change from one period to the next, not overfitting. Every report says so in its first callout.
2. **Folds are anchored by default, with a rolling option.** Windows are whole calendar years: by default a five-year first training window and one-year test windows. That gives 14 folds over 2005 to 2023, testing 2010 to 2023. `--rolling` keeps every training window at `--train-years` instead. Anchored is the default because a choice in PR 21 then rests on as many trades as the history allows. The rotation makes about nine round trips a year.

## Implementation choices made in PR 20, for review there

- **Every window is a backtest of its own, from the starting cash.** It runs through the same path as `tyche backtest` (`run_and_record`), warms up on the history before it, and starts flat. That is what PR 21 needs: each test window may run different parameters, so it cannot be a slice of one long run. The cost is that each test window pays to enter its positions again, and holds nothing on its first session. For buy-and-hold on SPY from 2010 to 2023, out-of-sample exposure is 95.8%.
- **The test windows are joined by chaining returns.** Each window's equity is scaled to start where the previous one ended. The benchmark (ADR-0025) is measured over each test window from the same starting cash and joined the same way. The move between one window's last close and the next one's first close counts as no change for both. Every window still trades the starting cash, not what earlier windows grew to, so minimum commissions weigh the same in each.
- **Windows are cut by date, in the core.** `plan_folds` uses calendar years only: the first training window starts on the first day asked for, and the last test window ends on the last day. A start late in a year makes the first training window shorter rather than moving the first test year. `measure_walk_forward` and `chain` are pure and in `Decimal`. The runtime runs the windows and writes the record.
- **The walk-forward stops at the first window that halts or cannot be measured.** It records what it ran up to there. Missing history stops it too, with the `tyche data fetch` command to run, and the windows already run stay recorded.
- **The record lives in `reports/walk_forward/<id>/`.** It holds:
  - `walk_forward.json`: code, config hash and snapshot, the scheme, the train step, every fold's windows and record folders, and the outcome.
  - `metrics.json`: the joined test windows against the joined benchmark, and how many test windows beat it.
  - `equity.csv`: both joined curves, with the fold of every close.
  - `report.html`.
  - `folds/<NN>-train/` and `folds/<NN>-test/`: each window's full backtest record, without a report of its own. Each `run.json` says which walk-forward, fold and window it belongs to (`part_of`).
- **One report per walk-forward, built from the record alone**, through the same renderer as the backtest report (ADR-0028). Sections:
  - out of sample: the test windows joined, with equity and drawdown charts;
  - fold by fold: in-sample CAGR and out-of-sample return, each against the benchmark, then Sharpe and drawdowns;
  - trading in the test windows;
  - what ran;
  - the limits every backtest shares, plus four a walk-forward adds.

  `tyche report <id>` rebuilds it, for a backtest or a walk-forward.
- **The scheme is set on the command line, not in the workspace config.** `--train-years`, `--test-years` and `--rolling` are written into `walk_forward.json`. Every existing workspace works unchanged. Trying several schemes on one strategy is also a form of trying many versions; PR 21 decides how trials are counted.

## Checked on real data

Yahoo data from 2004 to 2023 in a scratch workspace, USD 10,000, each strategy alone, `tyche walk-forward --from 2005-01-03` with the defaults (14 folds, testing 2010 to 2023):

| | Buy-and-hold (SPY) | Trend rotation | Mean reversion | SPY total return (benchmark) |
|---|---|---|---|---|
| Out-of-sample CAGR | 12.14% | 4.57% | 1.25% | 12.58% |
| Volatility | 16.57% | 12.33% | 5.45% | 17.29% |
| Sharpe (rf 0) | 0.78 | 0.42 | 0.25 | 0.77 |
| Max drawdown | 32.54% | 21.92% | 13.82% | 33.70% |
| Test windows ahead of the benchmark | 4 of 14 | 2 of 14 | 3 of 14 | |
| Time to run | 2 min 12 s | 2 min 46 s | 2 min 46 s | |
| Record size | 6.5 MB | 7.3 MB | 6.8 MB | |

What the rotation's folds show: its in-sample CAGR beat the benchmark's by 11 points on the first training window (2005 to 2009), and the lead shrank with every fold. From fold 7 on, the training window itself trails the benchmark. The lead came mostly from 2007 and 2008. In 2008 the rotation held Treasuries and gold and lost 4.5% while SPY lost 36.8%, and no test year from 2010 to 2023 repeated that. This is the "different periods" reading the first callout describes. It is not overfitting: nothing was fitted.

The buy-and-hold row checks the machinery. Its fold 14 training window (2005 to 2022) shows 8.34% against 8.73%. The joined test windows trail the benchmark by 0.44 points a year, close to the full-period cash drag found in PR 16 (0.50 points). Each test window's re-entry and empty first session add a little to that gap.

## Alternatives considered

- **Include a simple parameter choice in PR 20**, picking the best of several strategy files on each training window by a fixed rule. It completes the walk-forward in one PR, but takes over part of PR 21 and needs trial counting at once.
- **One fixed train/test split only**, such as 2005 to 2016 and 2017 to 2023. The smallest PR, but it delivers half of the brief's requirement.
- **Rolling folds only.** Adapts to regime changes, but every choice in PR 21 would rest on five years.
- **Slicing one long run into windows instead of running each window.** Faster, and for anchored windows with fixed parameters it gives the same training results. It cannot run different parameters in each test window, which is PR 21's whole point.
- **Carrying the account from one test window to the next.** Closer to a real account, but a new parameter choice then trades from whatever the last one left, which mixes the two.

## Consequences

- `tyche walk-forward --from <date>` runs, records and reports a walk-forward. `tyche report <id>` accepts a walk-forward's id.
- No workspace change is needed. A walk-forward reads the same cache as a backtest, and the holdout still bounds it (ADR-0024).
- **A walk-forward record is large**: about 7 MB with the defaults, because each of the 14 overlapping training windows keeps its full `equity.csv` and `fills.csv`. Compressed, as git stores it, one is about 1.9 MB, so a hundred walk-forwards add roughly 190 MB to a workspace repository. The training windows' `equity.csv` and `fills.csv` are 81% of the size; keeping only their `metrics.json` and `run.json` would cut it by about four fifths. Parameter sweeps multiply the number of runs, so PR 21 must settle what a run keeps.
- A walk-forward takes about 2 to 3 minutes on the nine-ETF profile, about ten times a single backtest of the same range: the anchored training windows replay 161 years between them.
- PR 21 plugs a parameter choice into the train step, and decides how a walk-forward counts as trials.

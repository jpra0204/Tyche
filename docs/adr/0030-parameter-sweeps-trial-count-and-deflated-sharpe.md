# ADR-0030: Parameter sweeps: every recorded trial counted, the pick by Sharpe ratio, and a deflated Sharpe ratio

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Phase 1, PR 21 adds what the brief asks for in section 6: "parameter sweeps, with warnings about overfitting", and what the Phase 0 review agreed on overfitting: every candidate ever tried is counted, and results are reported with a deflated Sharpe ratio or an equivalent correction for the number of trials. ADR-0029 left two things to this PR: plugging a parameter choice into the walk-forward's train step, and deciding how a walk-forward counts as trials. It also left the size of a run's record open: a walk-forward already writes about 7 MB, and sweeps multiply runs.

The problem a sweep has to face: try enough combinations and the best one looks good even when none has an edge. The best of 100 coin-flipping strategies has a fine Sharpe ratio. A sweep that reports its best result without saying how many tries stand behind it is overfitting presented as research.

Five questions came up before any code, and Pablo answered each one:

1. **One PR or two?** Splitting off the walk-forward train step was offered. One PR, as planned.
2. **What does the trial count include?** Every distinct trial of the plugin ever recorded in the workspace, not only the sweep's own combinations.
3. **What does a sweep keep on disk?** One table of every trial, and only the pick's full record.
4. **How is the pick chosen?** The highest Sharpe ratio.
5. **Where is the grid written?** A file in the workspace.

## Decision

1. **A sweep is a file**, `config/sweeps/<name>.toml`. It names one configured strategy (it needs a budget) and lists values per parameter under `[grid]`. Every combination of the values runs as a backtest over the same days; parameters not listed keep the strategy file's values, and the other configured strategies run alongside, unchanged. Every combination is built by the plugin before anything runs, so an unknown parameter or a value the plugin refuses stops the sweep with the sweep file named. Sweep files are read on demand and are not part of the config hash; a record states the sweep file's own hash beside the config hash.
2. **The pick is the highest Sharpe ratio** (risk-free rate zero, ADR-0025), the first in the grid's order on a tie. A trial with no Sharpe ratio (halted, not measured, no variation) is never picked. The deflated Sharpe ratio is defined on the Sharpe ratio, so the discount applies to exactly what was maximised.
3. **A trial is a plugin, its version and its full parameters.** Its fingerprint, `trial_key`, is a hash of the three. The count `N` behind a deflated Sharpe ratio is every distinct trial of the plugin found anywhere under `reports/`: each strategy of every `run.json` (backtests, walk-forward windows, sweep picks) and each combination of every `trials.json`, plus the sweep's own. Running the same trial again adds nothing. A change of any parameter, or of the plugin's rules (its version), is a new trial. A record Tyche cannot read stops the count with an error: a count that quietly drops trials makes every result look better.
4. **The deflated Sharpe ratio** is Bailey and López de Prado's (2014), equations 1 and 2: the chance that the pick's true Sharpe ratio is above zero, given `N`, the variance `V` of the trials' Sharpe ratios, the number of daily returns `T`, and their skewness and kurtosis. `V` is taken over **this sweep's** trials only, because they are the only ones measured over the same days as the pick. Sharpe ratios are per session inside the formula and annualised by √252 where shown. The pick is reported as significant at 95% or not. With a single trial counted, it is the probabilistic Sharpe ratio against zero.
5. **What a sweep keeps.** One `trials.json`: every combination's parameters, its trial key and its metrics, the pick, the trial count, the deflated Sharpe ratio with every input, and the warnings. Only the pick keeps a full backtest record (`run.json`, `metrics.json`, `equity.csv`, `fills.csv`). Any other trial can be run again from its parameters and the config hash. A standalone sweep writes `reports/sweeps/<id>/` with `sweep.json` (what ran), `trials.json`, `pick/` and `report.html`.
6. **The walk-forward's train step** (`tyche walk-forward --sweep <name>`) runs every combination on each training window and tests the pick on the test window after it. The training window's folder holds the pick's full record and that window's `trials.json`. Without `--sweep`, the train step still keeps the configured parameters (ADR-0029).
7. **How a walk-forward counts as trials.** Each combination of the grid is one trial, counted once however many training windows run it: the trial is the parameters, not the period. The joined out-of-sample result is **not deflated**, because nothing was chosen on it. Running several walk-forwards (other grids, other schemes) and keeping the best one is choosing again; the record and the report state the trial count so that it shows.

## Implementation choices made in PR 21, for review there

- **Overfitting warnings**, each a plain sentence in the terminal, `trials.json` and the report:
  - the deflated Sharpe ratio is below 95%, or could not be computed;
  - the pick sits at the first or last value of a parameter with three values or more: the best value may lie beyond the grid, and widening it adds trials;
  - the pick is an isolated peak: the median Sharpe ratio of its neighbours (one step of one parameter away) is below half its own. The one-half threshold is Tyche's choice, not the paper's;
  - some trials halted or could not be measured; they count in `N` and add nothing to `V`.
- **Every report of a sweep says first that the pick is in-sample**, and points to the walk-forward for an out-of-sample result.
- **`N` counts trials as if they were independent.** Neighbouring parameters trade alike, so the effective number of independent trials is lower. The paper's appendix 3 estimates it; Tyche does not, which makes the discount somewhat harsher than it needs to be. That errs on the side of caution, and the report says so.
- **The deflated Sharpe ratio is computed in `float`**, with `statistics.NormalDist` from the standard library: the normal quantile has no `Decimal` form. Every other metric stays in `Decimal` (ADR-0025). A test checks the paper's worked example: 0.9004 with 100 trials, 0.9505 with 46.
- **A run record now states each strategy's parameters** (`strategies[].parameters` in `run.json`), because a sweep's pick runs with parameters its strategy file does not hold. Records written before PR 21 have no such field; their config snapshot holds the strategy file, and the trial count reads it there. The record format number is unchanged: the field is added, nothing changes meaning.
- **Only the best run so far is held in memory** while a sweep runs; each other trial is reduced to its metrics as soon as it is measured.
- **The combination that needs the most history runs first**, then the others in the grid's order. History missing from the cache stops a sweep with the `tyche data fetch` command to run, and nothing is written; running the longest lookback first makes that happen before any other trial has spent time. Found on real data: the example grid's 252-session momentum needs history from December 2003, and the first attempt stopped at trial 7 after three and a half minutes. Trials keep their grid numbers, and the pick's tie rule is unchanged.
- **A new workspace ships an example sweep**, `config/sweeps/trend_rotation.toml`: holdings 2, 3 and 4; momentum over 63, 126 and 252 sessions; a trend average over 150, 200 and 250 sessions (27 combinations). The example strategies' rules were fixed in advance and must not be tuned on results (ADR-0027). Running the example sweep does not change that: it measures how much a search over them is worth, and every combination it runs counts as a trial from then on.

## Checked on real data

Yahoo data from 2003 to 2023 in a scratch workspace, USD 10,000, the trend rotation alone, the example sweep (27 combinations) from 2005-01-03 to 2023-12-29. One backtest of the configured rotation was recorded first, as in any workspace that ran PR 18; its parameters are in the grid, so 27 trials were counted.

| | Pick (trial 26) | Configured (trial 14) | SPY total return (benchmark) |
|---|---|---|---|
| Parameters | 4 holdings, 252-session momentum, 200-session trend | 3, 126, 200 | |
| CAGR | 8.28% | 5.97% | 9.59% |
| Sharpe (rf 0) | 0.71 | 0.49 | 0.57 |
| Max drawdown | 19.54% | 29.68% | 55.20% |
| Closed trades | 136 | 175 | |

- The 27 Sharpe ratios ran from 0.34 to 0.71. The configured trial reproduced PR 18's figures exactly.
- **Deflated Sharpe ratio of the pick: 98.2%**, significant at 95%. Inputs: `N` = 27, `V` = 5.15 × 10⁻⁵ per session, `T` = 4,780, skewness -0.27, kurtosis 6.93. The Sharpe ratio luck alone was expected to reach was 0.23 annualised.
- **Two warnings**: the pick's holdings (4) and momentum (252) are both the last values of their lists.
- **What 98.2% does not say.** Its null hypothesis is a true Sharpe ratio of zero, a low bar over 19 years. Holding SPY clears it too: the same formula gives the benchmark 99.3% against zero. The deflated Sharpe ratio says the pick is unlikely to be pure luck. It does not say the pick beats the benchmark: its CAGR trails SPY's by 1.3 points a year, and its higher Sharpe ratio was found in-sample, at the edge of the grid. Whether the Phase 3 gate should deflate against the benchmark's Sharpe ratio rather than zero is left open (`STATUS.md`).
- The sweep took 16.5 minutes with another run sharing the machine. Its record is 968 KB, of which the pick's full record is 704 KB.

A walk-forward with the same sweep (`tyche walk-forward --from 2005-01-03 --sweep trend_rotation`, the default 14 folds, testing 2010 to 2023), added after PR 21 merged because it was still running then:

| Out of sample, 2010 to 2023 | Sweep picks on each training window | Configured parameters (PR 20, no sweep) | SPY total return |
|---|---|---|---|
| CAGR | 4.29% | 4.57% | 12.58% |
| Sharpe (rf 0) | 0.42 | 0.42 | 0.77 |
| Max drawdown | 21.26% | 21.92% | 33.70% |
| Test years ahead of the benchmark | 3 of 14 | 2 of 14 | |

- **The picks did not settle.** Seven different combinations were picked across the 14 training windows: 252-session momentum in fold 1, then 63 sessions with 2, 3 or 4 holdings for folds 2 to 10, then 252 sessions with 4 holdings for folds 11 to 13, then 63 sessions again.
- **13 of the 14 training picks were significant**: deflated Sharpe ratios from 94.3% (fold 2) to 98.9% (fold 13), with 27 trials counted. Out of sample they earned no more than the parameters fixed in advance, and a third of the benchmark's return.
- This is the case the deflated Sharpe ratio cannot catch on its own. A pick can be very unlikely to be pure luck over its training years and still carry no advantage into the next year. Choosing among these parameters by in-sample Sharpe ratio bought nothing.
- It took 2 hours 22 minutes, sharing the machine with another run for part of it. The record is 7.8 MB.

## Alternatives considered

- **Counting only the sweep's own combinations.** Simpler, but a second sweep run after seeing the first would start from zero and hide the search that came before.
- **Keeping every trial's full record, or each trial's `run.json` and `metrics.json`.** Every trial would be a normal record, at roughly 27 times the size of a walk-forward, or hundreds of folders repeating the same config snapshot.
- **Picking by CAGR, or by Sharpe ratio with a minimum number of trades.** CAGR rewards concentration, and the deflation would discount a statistic other than the one maximised. A minimum trade count is one more threshold to justify, and the deflated Sharpe ratio already accounts for the length of the history.
- **The grid on the command line.** No file to write, but long grids are awkward to type and the history of grids would live only in the records.
- **The Probability of Backtest Overfitting** (Bailey et al., 2014). Non-parametric and informative, but it needs many combinations evaluated over many splits of the history; the deflated Sharpe ratio works from what one sweep already measures.
- **Two PRs**, the walk-forward train step after the sweep itself. Offered; Pablo chose one.

## Consequences

- `tyche sweep <name> --from <date>` runs, records and reports a sweep; `tyche walk-forward --sweep <name>` picks parameters on each training window; `tyche report <id>` rebuilds a sweep's report too.
- Every trial recorded in a workspace makes the next sweep of that plugin harder to pass. That is the point: the count only grows, and deleting records to lower it would defeat it. The workspace is a git repository, so its history keeps them anyway.
- Sweeps are slow: each combination is a full backtest, and a walk-forward with a sweep runs every combination on every training window. With anchored folds, the training windows replay 161 years between them for each combination. Running each combination once to the last training window and measuring its prefixes would give the same anchored training results in a fraction of the time; that is left for when it is needed (ADR-0005 already expects parallel processes for sweeps).
- The Phase 3 gate's trial registry (`tyche.core.improvement`) can start from `trial_key` and `recorded_trial_keys`.

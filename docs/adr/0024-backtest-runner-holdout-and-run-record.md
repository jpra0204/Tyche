# ADR-0024: The backtest runner: a fixed holdout, candidates in the market profile, and a run record

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Phase 1, PR 15 runs the first end-to-end backtest. Three questions had to be settled first:

1. **How much recent history to reserve.** The system overview and the agent architecture promise a holdout from the first backtest on: the most recent history, never replayed by any experiment, used once for the final check before a promotion (Phase 3). A holdout that earlier experiments have seen is not a holdout, so it had to exist before the first backtest.
2. **Which instruments a backtest replays.** The universe rules decide which instruments are eligible, but nothing in the configuration listed the candidates.
3. **What a run leaves behind.** The brief asks that every result be saved with its exact config and code version, so that it can be reproduced. The Phase 3 gate and the parameter sweeps (PR 21) will also count trials, so every run must leave a trace.

## Decision

1. **The holdout starts on a fixed date: 2024-01-01.** It is set in the workspace, `holdout_starts` under `[backtest]` in `config/tyche.toml`. A backtest whose last day is on or after it is refused, before any data is read. The date never slides forward with time, so the holdout grows: about 2.9 years today, about 11% of the history since 2000. Moving it later would hand history some experiments have seen to the final check, and must not be done.
2. **The candidates are listed in the market profile.** `instruments` under `[universe]` in `config/markets/<NAME>.toml`, each with its symbol, exchange and asset class. A backtest replays exactly these; paper and live will fetch exactly these. The list is part of the config hash. The universe rules still decide, at every decision, which candidates are eligible.
3. **Every run leaves a record in the workspace.** `reports/backtests/<run id>/` holds `run.json`, `equity.csv` and `fills.csv`. A run that halts is recorded too.

## Implementation choices made in PR 15, for review there

- **The holdout is checked twice.** The runtime checks the requested range before building anything; the core runner checks it again, loads history only up to the last day, and refuses to run if the data provider returns any bar after that day. A bug in a provider cannot leak holdout prices into a run.
- **No way around it in Phase 1.** There is no option to backtest into the holdout. The Phase 3 promotion check will be the one code path allowed to use it, and its use will be recorded.
- **A backtest reads the cache only.** The cache is read through a source that never fetches (`CacheOnlySource`). Missing history stops the run with the exact `tyche data fetch` command to run. A backtest therefore never downloads during a run, and two runs on the same cache see the same prices even though Yahoo revises history.
- **The runner lives in the core and takes a `DataProvider`.** `tyche.core.backtest.run_backtest` wires the same stages as paper and live will, with `SimClock`, `HistoricalReplay` and `SimBroker`; it does no I/O. `tyche.runtime.backtest` chooses the calendar, the cache and the clock, and writes the record.
- **Warm-up uses the sessions before the first day.** The runner asks the stages how much history they need (the universe's liquidity average and data-issue memory, each strategy's lookback), loads that many sessions before the first day, and warms both stages up through one path each: `UniverseStage.warm_up` and `SignalsStage.warm_up` (ADR-0021). Nothing is published and nothing trades during warm-up. If the calendar starts too late, the warm-up is shorter and the record says so.
- **The starting cash is a setting.** `starting_cash` under `[backtest]`, settled, in the profile's cash currency. The template says `"10000"`; a small account pays proportionally more in minimum commissions, so it should be the amount you would really trade.
- **The run id** is the start time in UTC and the first eight characters of the config hash, `20261119T172646Z-75505646`; a second run in the same second gets `-2`.
- **The code version** is the package version plus the git commit, with `.dirty` when tracked files have uncommitted changes or the source tree has new files. A dirty run is allowed, recorded and warned about, because the commit alone does not reproduce it.
- **What `run.json` holds:** the record format, run id, start and end times, the code version (package, commit, dirty, Python), the config hash and every setting behind it (`TycheConfig.snapshot`, exactly what was hashed), the range and sessions replayed, the warm-up asked for and got, the holdout start, the starting cash, the rebalance band and price buffer, the date the costs were checked, each strategy (id, plugin, version, budget), the data used per instrument (source, bars, first and last bar, when it was fetched, issues, distributions, splits), and the outcome (completed or why it halted, events, fills, free-riding violations, final equity and cash, and whether Tyche's account view agrees with the broker's).
- **Records are committed with the workspace.** They live under `reports/`, which the workspace's `.gitignore` does not exclude. `equity.csv` is about 4,800 rows for 2005 to 2023.

## Alternatives considered

- **A holdout of the last N years, computed from today.** Slides forward every day, turning last year's holdout into this year's training data.
- **A shorter holdout (from 2025).** More history for research, but too few trades for a slow strategy to make the final check meaningful.
- **A longer holdout (from 2023).** A stronger final check, at the cost of a year less for in-sample and walk-forward testing.
- **Candidates in their own file, or on the command line.** A file of its own behaves the same with one more file to keep. A command-line list would be outside the config hash and would have to be retyped; paper and live would need a config list anyway.
- **Every instrument in the cache.** Implicit: fetching a new symbol would change every later backtest without changing the config hash.
- **Fetch missing history during the backtest.** Convenient, but a run's prices would depend on when it ran.

## Consequences

- `tyche backtest --from <date>` runs the configured strategies from the cache and prints where the record is.
- Every workspace needs a `[backtest]` table in `config/tyche.toml` and an `instruments` list under `[universe]` in `config/markets/US.toml`.
- A strategy can only trade instruments listed as candidates. `tyche config check` cannot see which instruments a strategy names, so one naming an unlisted instrument simply never trades; the record's fill count shows it.
- History from 2024-01-01 on is out of reach for every Phase 1 and Phase 2 experiment, walk-forward included.
- The metrics (PR 16) read `equity.csv` and `fills.csv`, or the `BacktestResult` directly.

# The holdout and the run record

## What problem does this solve

Two ways a backtest lies to you without a single bug in it:

1. **You tune on the answer.** Try ten ideas on 2005 to 2023, keep the best, and its result is partly luck: the luck of fitting that particular history. Judging it on the same history cannot tell skill from luck. Every extra experiment makes it worse, and it is invisible in any one result.
2. **You cannot say what produced a number.** Six weeks later, "+421%" means nothing unless you know which code, which settings and which data made it. Without that, a result cannot be reproduced, compared or trusted.

## The idea

**A holdout** is a slice of history set aside before any experiment and never looked at until the end. It is used once, for the final check. Because nothing was chosen on it, a strategy that still beats the benchmark there has passed an honest test. Two details matter:

- It must be reserved *before* the first experiment. A holdout someone has already looked at is just more training data.
- Its start must be fixed, not "the last two years". A sliding window turns last year's holdout into this year's training data without anyone noticing.

**A run record** is written by every run, whatever its result: which code ran (version and commit, and whether there were uncommitted changes), every setting (and a hash that fingerprints them), which data (and when it was fetched), and what happened. Recording the failures too is what makes it possible to count how many things were tried before something worked, which the overfitting checks later need.

## Where is it in Tyche

- `BacktestSettings` (`tyche.core.backtest.settings`) holds `holdout_starts`, read from `[backtest]` in the workspace's `config/tyche.toml`. `require_before_holdout` refuses any run that reaches it, in the runtime and again in the core runner, which also refuses a data provider that returns bars past the run's last day ([ADR-0024](../adr/0024-backtest-runner-holdout-and-run-record.md)).
- `tyche.runtime.backtest` writes `reports/backtests/<run id>/run.json` with the code version (`current_code_version`), the config hash and `TycheConfig.snapshot` (exactly what was hashed), the data used and the outcome, plus `equity.csv` and `fills.csv`.
- A backtest reads only the cache (`CacheOnlySource`), so a run never depends on when it was run: Yahoo revises history, and the record says when the data was fetched.

## What does it cost

- **Less history to learn from.** From 2024-01-01 on, about 11% of the history since 2000 today, is out of reach for every experiment until Phase 3. That is the price of having an honest final test.
- **Discipline the code cannot enforce.** The date is in your own config file. Moving it later would quietly ruin it; only you can keep that rule.
- **A holdout is spent once.** After the final check, it has been seen. A strategy that fails it must not be tweaked and re-checked on the same slice.
- **Records pile up.** One folder per run, kept in your workspace's git history. That is deliberate: the pile is the trial count.

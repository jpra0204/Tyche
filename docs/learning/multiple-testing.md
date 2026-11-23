# Multiple testing and the deflated Sharpe ratio

## What problem does this solve

Try enough versions of a strategy and one of them will look good by luck. Toss 27 coins ten times each and the luckiest will show seven or eight heads; nobody would call that coin skilled. A parameter sweep does the same with backtests: the best of 27 combinations has a higher Sharpe ratio than a typical one even when none has an edge. Reporting the best result alone, without the number of tries behind it, turns luck into a discovery. This is **selection bias**, and it is the most common way a backtest overstates what a strategy can do.

## The idea

Count every try, and judge the winner against what the best of that many tries would reach by luck.

1. **Count trials, for good.** A trial is one distinct version of a strategy: its plugin, its rules (version) and its full parameters. Every trial ever recorded counts, not only those in the latest sweep, because each result seen shaped what was tried next. The count only grows.
2. **Ask what luck alone gives.** If `N` trials with no skill have Sharpe ratios spread with variance `V`, the best of them is expected to reach about `SR0 = √V · ((1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)))`, where `γ ≈ 0.5772` and `Z⁻¹` is the normal quantile. More trials, or more varied results, raise the bar.
3. **Ask how sure the winner's Sharpe ratio is.** A Sharpe ratio estimated from `T` daily returns is uncertain, more so when returns are skewed to the left or have fat tails. The **deflated Sharpe ratio** is the probability that the winner's true Sharpe ratio is above zero once its own measured value is compared with `SR0`, given `T`, skewness and kurtosis (Bailey and López de Prado, 2014). Below 95%, the winner is not distinguishable from the best of `N` tries with no edge.

A worked example from the paper: an annualised Sharpe ratio of 2.5 over five years of daily returns sounds remarkable. After 100 trials whose Sharpe ratios had an annualised variance of 1/2, with negatively skewed, fat-tailed returns, the deflated Sharpe ratio is 90%, below the 95% bar. After 46 trials it would have been 95%.

Two things the deflated Sharpe ratio does not do: it does not test out of sample (the walk-forward does), and it does not say the winner beats the benchmark. It says only how likely the winner is to be more than luck.

## Where is it in Tyche

- `src/tyche/core/backtest/sweep.py`: `combinations` of a `Grid`, `pick` (highest Sharpe ratio), `trial_key`, `expected_max_sharpe`, `probabilistic_sharpe`, `deflated_sharpe` and `overfitting_warnings`. Pure, no I/O; a test checks the paper's example.
- `src/tyche/runtime/trials.py`: `recorded_trial_keys` reads every `run.json` and `trials.json` under `reports/` and returns the distinct trials of a plugin.
- `src/tyche/runtime/sweep.py`: `tyche sweep <name>` runs every combination of `config/sweeps/<name>.toml`, picks, deflates, and writes `reports/sweeps/<id>/`.
- `tyche walk-forward --sweep <name>`: picks on each training window and tests the pick on the year after.
- [ADR-0030](../adr/0030-parameter-sweeps-trial-count-and-deflated-sharpe.md) records the choices.
- `tyche compare-profiles` is the other side of the same idea. Comparing risk profiles adds no trial, because the strategies' parameters do not change, so it **picks nothing**: the report warns that choosing the best-looking profile is a selection that nothing corrects for ([ADR-0036](../adr/0036-risk-profiles-side-by-side.md)). Where a correction would be awkward, refusing to choose is the honest alternative.

## What does it cost

- **Every try makes the next one harder.** That is the intent, but it means a careless sweep spends something that cannot be recovered. Plan a grid from reasons, not from results.
- **Trials are treated as independent.** Neighbouring parameters trade alike, so there are fewer really different tries than `N` says, and the discount is harsher than it strictly needs to be.
- **Only what is recorded is counted.** Ideas tried in a spreadsheet, or read about in a paper, are not in the count.
- **Time.** Every combination is a full backtest; inside a walk-forward, every combination runs on every training window.

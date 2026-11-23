# ADR-0036: Risk profiles side by side, with no trials added and no pick, and one small-account profile per live stage

- **Status:** Proposed
- **Date:** 2026-11-23

## Context

The brief asks that "backtests can run the same strategy under several profiles side by side, so I can compare them" (§7.2), and for "risk-profile sweeps, with warnings about overfitting" (§6). Phase 2, PR 5 delivers it. Two questions came with it, and [ADR-0031](0031-minimum-viable-capital.md) left a third open: what risk profile a small account should trade under. [ADR-0035](0035-account-rules-and-the-drawdown-halt.md) added a fourth: the walk-forward, sweep and capital reports should say which of their runs the drawdown kill halted.

Pablo answered three questions on 2026-11-23, before any code:

1. **Does comparing profiles add to a plugin's trial count?** No, but the comparison picks nothing, and it warns. A trial stays a plugin, its version and its parameters ([ADR-0030](0030-parameter-sweeps-trial-count-and-deflated-sharpe.md)), so every existing count is unchanged.
2. **What shape should the small-account profile take?** One profile per live stage, tightening as capital grows: `stage-1` (1 position up to 100%), `stage-2` (2 up to 50%), `stage-3` (4 up to 25%). Risk per trade 1%, daily loss 3% and drawdown kill 15%, as in `default`.
3. **Where do they live?** In the user guide, not the template. The template guardrails cap a position at 25%, so `stage-1` and `stage-2` would fail there. Pablo creates the profiles in his own workspace and sets its guardrails himself.

## Decision

**`tyche compare-profiles --from <date> [--to <date>] [--risk-profile <name>]...`** runs the configured strategies once per risk profile, over the same days, from the same cache. Without `--risk-profile`, it compares every profile in `config/risk/`, in name order; with it, the named ones in the order given. At least two are needed, each named once. Only the risk profile changes between runs: the strategies, their parameters, the starting cash and the costs are the same.

**What it keeps**, in `reports/profiles/<id>/`:

- `profiles.json`: what ran (code, range, starting cash, strategies, benchmark), and per profile its values, its config hash (which covers that profile, so each differs) and its run's folder and outcome. `trials_added` is always 0.
- `runs/<profile>/`: each profile's full backtest record, as `tyche backtest` writes it, with `part_of` naming the comparison. The trial count reads these like any other `run.json`, and finds the trials it already had.
- `report.html`: every profile side by side against the benchmark (final equity, return, CAGR, volatility, Sharpe, Sortino, max drawdown, exposure, costs, closed trades); equity and drawdown charts with one line per profile, each halt marked; a table of what each profile's limits did (gate cuts, daily loss triggers, the halt date and the share of the range still to run); what ran; and the data's limits. `tyche report <id>` rebuilds it.

**It names no best profile.** A callout at the top says how many profiles were compared, that choosing the best-looking one is a selection like picking from a sweep, that nothing here corrects for it, and that a profile is chosen for the account and the losses Pablo can sit through. Each halted profile gets its own warning with the share of the range it spent not trading.

**Halts in the other studies.** Each sweep trial in `trials.json` and each run in `capital.json` gains `halted_at` (the close, or `null`). The sweep, capital and walk-forward reports open with a warning naming every run the drawdown kill halted, with its date. A walk-forward reads it from each window's `run.json`.

**The stage profiles** are documented in the user guide, with the guardrails each needs.

## Alternatives considered

- **The profile in the trial key** (each strategy and profile pair a trial). Stricter, but every record since Phase 2, PR 2 would be re-keyed and every count and deflated Sharpe ratio already reported would change. Rejected by Pablo.
- **Deflate within the comparison** (N = profiles compared). It would attach a significance figure to choosing a profile by Sharpe ratio, which is the use the comparison is meant to discourage. Rejected by Pablo.
- **Repeat `--risk-profile` on `tyche backtest`.** Natural to type, but one command would then write either one record or a folder of them, and its summary could not be the same. A separate command keeps `tyche backtest` simple.
- **One `small` profile for every stage, or two profiles.** One profile cannot fit both USD 700 and about USD 7,000. Two leave stage 2 with slots too small for some funds. Rejected by Pablo.
- **Ship the stage profiles in the template**, raising the template's position ceiling to 100%. Every new workspace's guardrails would then allow a single position of the whole account. Rejected by Pablo.

## Consequences

- **A profile only ever lowers what a strategy asks for.** It never scales a strategy up to fill its slots. The trend rotation asks for a third of the account in each of three funds, so under `stage-1` it holds one fund at a third and leaves the rest in cash. To use a one-position profile fully, a strategy has to ask for one position: for the rotation, `holdings = 1`, which is a parameter change and so a new trial.
- **On real data, a 15% drawdown kill trips early under concentrated profiles.** From 2005 to 2023, USD 10,000, the rotation under `stage-2` and `stage-3` halted on 2006-06-13, with 92% of the range still to run; under `default` on 2020-03-18; under `stage-1` never, because it was only a third invested. A halted run's later results are not evidence about the strategy, and the report says so. Whether 15% is the right kill for a concentrated profile is a question for the profile, and this comparison is where to look at it.
- **Comparisons are cheap and tempting.** Every profile added makes the best one look better by chance. The warning cannot stop that; only the discipline of choosing a profile for reasons outside the results can.
- **Research backtests still ignore the money caps**, so a comparison at the workspace's `starting_cash` says nothing about whole shares at a small account. `tyche capital` does; changing `starting_cash` in a scratch workspace runs a comparison at a stage's size.

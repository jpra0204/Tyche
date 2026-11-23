# Troubleshooting

Problems and questions across Tyche, as of the end of Phase 1. Each page of this guide also has its own table for its own commands; this page collects what cuts across them, and grows with every phase.

## First checks

1. **Is Tyche looking at the right workspace?** It uses `--home`, then `TYCHE_HOME`, then `~/tyche-workspace`. `uv run tyche config check` prints the folder it found.
2. **Is the configuration valid?** `uv run tyche config check` names the file and the setting of any problem. Every command checks it the same way before doing anything.
3. **Are you running the code you think?** `uv run tyche --version`, from the Tyche code folder. Every record also states the code version and commit it ran with.

## Upgrading a workspace created by an older Tyche

`tyche init` never touches an existing workspace, so a workspace keeps the files of the version that created it. When a later version needs something new, the error names the file and the setting. The fix is always the same: create a scratch workspace with the new version and copy what is missing, comments included.

```bash
uv run tyche init --home /tmp/tyche-fresh
```

| Missing | Added in | Copy from the scratch workspace into yours |
|---|---|---|
| `config/costs/US.toml` | PR 9 | The whole file |
| `[universe]` in `config/markets/US.toml` | PR 11 | The table |
| `[strategies]` in `config/tyche.toml` | PR 13 | The table, and `config/strategies/buy_and_hold.toml` |
| `[execution]` in `config/markets/US.toml` | PR 14 | The table |
| `[backtest]` in `config/tyche.toml` | PR 15 | The table |
| `instruments` under `[universe]` | PR 15 | The list; nine ETFs since PR 18 |
| `[benchmark]` in `config/markets/US.toml` | PR 16 | The table |
| `config/strategies/trend_rotation.toml`, `mean_reversion.toml` | PR 18 | The files, if you want to try the example strategies |
| `config/sweeps/trend_rotation.toml` | PR 21 | The file, if you want the example sweep |
| `[tiered]` in `config/costs/US.toml` | PR 22 | The table, if you want `tyche capital` to compare Tiered. Optional: without it, Fixed only |
| `config/guardrails.toml` and `config/risk/default.toml` | Phase 2, PR 1 | Both files. Tyche refuses to start without its hard limits. The guardrail values are an example: set your own ([risk profiles](08-risk-profiles.md)) |

Copying changes your config hash, as any change of setting does: runs before and after the copy are told apart in their records. That is intended.

Then delete the scratch workspace.

## Messages any command can print

| Message | What to do |
|---|---|
| `config/tyche.toml is missing; is … a Tyche workspace?` | Tyche is looking in the wrong folder: check `TYCHE_HOME` and `--home`. |
| `… Field required` | Something added in a later version is missing; see the table above. |
| `… Extra inputs are not permitted` | A misspelled or unknown setting. Unknown settings are always an error, so a typo is never silently ignored. |
| `write decimals as strings, such as "0.005", so they stay exact` | Put quotes around the number: `"0.005"`, not `0.005`. |
| `… is the reserved holdout; end the backtest before 2024-01-01` | Any command that backtests refuses the holdout. Give an earlier `--to`, or leave it out. |
| `… are not in the cache yet. Fetch it first:` | Run the `tyche data fetch` command printed below it, then the same command again. |
| `… has no budget under [strategies]` | A sweep names a strategy that does not run. Give it a budget in `config/tyche.toml`. |
| `no strategy has a budget under [strategies] in tyche.toml, so there is nothing to analyse` | `tyche capital` analyses the strategies with a budget; give the ones you want one. |
| `Error: the run halted: …` | A stage found something it could not handle and stopped rather than guess. The record is still written. This usually means a bug: keep the record and share the message. |
| `Warning: the code had uncommitted changes …` | The result is fine, but its commit alone does not reproduce it. Commit, or rerun from a clean checkout, before keeping the result as evidence. |

## Questions

**Why does Tyche's buy-and-hold trail the benchmark?** The benchmark reinvests every dividend at once, pays no costs and holds no cash. Tyche's buy-and-hold keeps the price buffer and dividends in cash until the rebalance band is crossed. About half a point a year over 2005 to 2023 ([running a backtest](03-running-a-backtest.md#reading-a-buy-and-hold-run)).

**A result looks too good. What should I check?** Whether it is in-sample (a single backtest or a sweep's pick), how many trials stand behind it (the sweep's trial count), and the walk-forward's out-of-sample result. Then the account size: `tyche capital` shows what your real account would lose to costs and whole shares.

**Can I delete old records to tidy up?** Not records of runs you looked at. Trials are counted from them: deleting them makes every later deflated Sharpe ratio look better than it is ([parameter sweeps](05-parameter-sweeps.md#the-record)).

**Why does `tyche data fetch` report missing sessions for GLD and VNQ before late 2004?** They did not exist yet. That is expected, and the sessions are marked as asked for, so no command asks again.

**Which runs may I do on my real workspace?** All of them write records there, which is what records are for. Tests and Claude Code sessions use a scratch workspace (`--home`), never yours.

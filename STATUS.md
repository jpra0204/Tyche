# Status

*Last updated: 2026-11-20*

## Current phase

**Phase 1: core and backtesting (`US`, end of day). In progress.** Pablo agreed the PR list below on 2026-11-16.

- Phase 0 is merged.
- PR 1 (domain types) is merged.
- PR 2 (event envelope and bus) is merged.
- PR 3 (clock and calendar) is merged.
- PR 4 (workspace and config) is merged; ADR-0017 accepted.
- PR 5 (data port and Parquet cache) is merged.
- PR 6 is merged: 6a directly, 6b through #9 (it first landed on the 6a branch because its stacked base was not retargeted in time).
- PR 7 (engine and replay feed) is merged.
- PR 8 (account ledger) is merged.
- PR 9 (costs and settlement) is merged; ADR-0020 accepted.
- PR 10 (`SimBroker`) is merged.
- PR 11 (universe and screening) is merged.
- PR 12 (strategy interface and benchmark) is merged; ADR-0021 accepted.
- PR 13 (portfolio construction and strategy config) is merged; ADR-0022 accepted.
- PR 14 (risk gate and execution) is merged; ADR-0023 accepted.
- PR 15 (backtest runner) is merged; ADR-0024 accepted. **Milestone reached: the first end-to-end backtest.**
- PR 16 (metrics) is merged; ADR-0025 accepted.
- PR 17 (reference validation) is merged; ADR-0026 accepted.
- PR 18 (example strategies) is merged; ADR-0027 accepted.
- PR 19 (backtest report) is open for review; ADR-0028 accepted: one self-contained HTML file per run with matplotlib charts, and a cost drag measured by adding costs back onto equity.
- Recommended: turn on *Automatically delete head branches* in the GitHub repository settings, so GitHub retargets stacked PRs by itself.
- Adjusted prices decided 2026-11-17: split-adjusted prices with dividends as cash events ([ADR-0019](docs/adr/0019-split-adjusted-prices-and-cash-dividends.md)).

## What works today

- `uv sync` installs a pinned Python 3.14 environment.
- `make check` passes: ruff lint and format, mypy strict, six import-linter architecture contracts, pytest.
- `tyche --version` runs.
- CI runs the same checks on every pull request and on `main`.
- Domain types (PR 1): `Currency`, `Money`, `Timeframe`, `Instrument`, `Bar`.
- Event bus (PR 2): `Event`, `Envelope`, `EventBus`.
- Clock and calendar (PR 3): `Clock` and `Calendar` ports, `Session`, `SimClock`, and an NYSE calendar backed by `exchange_calendars`.
- Workspace and config (PR 4): `tyche init` creates a private workspace; `tyche config check` validates it and prints the config hash. The CLI is built with Typer.
- Data layer (PRs 5, 6a and 6b): `DataProvider` port, data-quality audit, Parquet cache, read-through provider, dividends and splits, and the Yahoo Finance source. `tyche data fetch` downloads real data into the workspace.
- Engine and replay (PR 7): one run loop for every mode; history replayed session by session with no lookahead; an in-memory journal that traces any event to its cause. Checked end to end, from data source to journal.
- Universe and screening (PR 11): `UniverseStage` decides at every decision cycle which instruments are eligible under the market profile's new `[universe]` rules (profile membership, a current bar, no recent data problem, enough history, a minimum price, a minimum average dollar volume) and says why each other one is excluded. `ScreeningStage` ranks the eligible ones with a `Screen`; the first, `DollarVolumeScreen`, ranks by liquidity. Events `UniverseEvent` and `ScreeningEvent`.
- Strategy interface and signals (PR 12): the `Strategy` contract ([ADR-0021](docs/adr/0021-strategies-see-a-window-handed-in.md)). Each strategy declares a timeframe and a lookback and, at every cycle, is handed a read-only `StrategyContext`: the ranking, exactly `lookback` bars per offered instrument, the instruments still warming up, and its own positions (empty until PR 14). `SignalsStage` keeps windows per instrument and timeframe, fills them through one warm-up path (`warm_up`), checks every strategy's targets and records a failing strategy without halting the run. Events `SignalEvent` and `SignalsReadyEvent`. The benchmark `BuyAndHold` in `tyche.strategies`.
- Portfolio construction and strategy config (PR 13): `PortfolioStage` turns each cycle's signals into a proposed `TargetPortfolioEvent` in weights of account equity ([ADR-0022](docs/adr/0022-portfolio-targets-as-weights-in-sleeves.md)): one sleeve per strategy (budget, decided or failed, the instruments it decided on), and per instrument the sum of each strategy's `budget × weight`, each contribution with its own stop. What a sleeve holds outside what it decided on is kept, said by the event itself. Strategies are configured in the workspace: budgets under `[strategies]` in `tyche.toml`, one `config/strategies/<id>.toml` per instance naming a built-in plugin and its strictly checked parameters; `tyche config check` builds them and prints the budgets and the cash left.
- Simulated broker (PR 10): `SimBroker` fills market orders at the next open and sell stops against each bar's low, with slippage, volume-capped partial fills, settled-cash-only purchases, T+1 settlement, free-riding records and dividends credited at the ex-date. The `Broker` port, and the `OrderEvent`, `FillEvent` and `DistributionEvent` events. The replay now publishes distributions.
- Costs and settlement (PR 9): IBKR Pro Fixed commissions and regulatory fees, adverse slippage, whole-share sizing that leaves room for costs, and T+1 settlement dates, with the rates in a dated `config/costs/US.toml`. `tyche config check` prints when the rates were checked.
- Account ledger (PR 8): orders with a checked lifecycle, fills, positions at average cost, and cash per currency, settled and unsettled. Refuses short sales, buying beyond the cash, and applying a fill twice.

- Risk gate and execution (PR 14): `PassThroughGate` approves every proposed portfolio unchanged (risk rules come in Phase 2). `ExecutionStage` turns approved weights into whole shares of equity at the last close, keeps a holding within the rebalance band, crosses shares between sleeves and nets the rest into one market order per instrument, fits purchases to the buying power at the next open with a price buffer, splits fills between sleeves pro rata, and places each protective stop when its entry fills ([ADR-0023](docs/adr/0023-execution-sleeves-stops-and-cash.md)). `SleeveBook` gives each strategy its own positions; `AccountState` keeps Tyche's own view of the account and publishes an `AccountEvent` at every close. One `ExecutionPlanEvent` per decision says what each sleeve held, aimed for and ordered, and why. `SimBroker` now cancels on request and pays purchases from buying power (a fix: two purchases at one open could spend the same cash). `[execution]` in `config/markets/US.toml`: `rebalance_band = "0.10"`, `price_buffer = "0.02"`. Checked end to end from workspace config to fills on the real NYSE calendar.

- Backtest runner (PR 15): `tyche backtest --from <date>` runs the configured strategies on cached history through the whole trading path ([ADR-0024](docs/adr/0024-backtest-runner-holdout-and-run-record.md)). It replays the candidates now listed under `[universe]` in `config/markets/US.toml`, warms up the universe and the strategies on the sessions before the first day, reads the cache only (missing history stops it with the `tyche data fetch` command to run), and refuses any range reaching the holdout (`holdout_starts = 2024-01-01` under `[backtest]` in `tyche.toml`, with `starting_cash`). Every run writes `reports/backtests/<run id>/`: `run.json` (code version and commit, config hash and every setting, range, warm-up, data used, outcome), `equity.csv` and `fills.csv`. Checked on real Yahoo data in a scratch workspace: SPY buy-and-hold from 2005-01-03 to 2023-12-29, 4,781 sessions in about 6 seconds, 10,000 to 52,168 USD, three fills, no free riding, Tyche's account view equal to the broker's.

- Metrics (PR 16): every backtest is measured against the benchmark named in the new `[benchmark]` table of `config/markets/US.toml` (SPY): its total return, with distributions reinvested at the ex-date close, no costs and no cash, from the same equity on the same closes ([ADR-0025](docs/adr/0025-metrics-against-the-benchmarks-total-return.md)). CAGR, volatility, Sharpe and Sortino (risk-free rate zero), maximum drawdown with its dates, exposure, turnover, costs, closed trades and win rate, and each difference from the benchmark. `tyche backtest` prints them; the record gains `metrics.json` and a `benchmark_equity` column. A golden-file test pins every figure of a fixed run. Checked on real data, SPY 2005 to 2023: Tyche's buy-and-hold 9.09% a year against the benchmark's 9.59% (the cash drag); the benchmark grows 5.6875 times against 5.6839 for Yahoo's own adjusted close.

- Reference validation (PR 17): one strategy (hold 95% of equity while the close is above its recent average) runs through Tyche and through backtesting.py on the same bars, and every fill, the equity at every close, every closed trade and the metrics are compared ([ADR-0026](docs/adr/0026-reference-validation-against-backtesting-py.md)). Tyche runs as the `US` profile configures it, without regulatory fees, which backtesting.py cannot model; slippage is charged to backtesting.py as commission. In CI: a seeded random walk, 2021 to 2023, at USD 10,000 and USD 1,000,000, 53 round trips each. Opt-in: real SPY from 2005 to 2023, 173 round trips over 4,781 sessions, final equity equal to 11 decimal places. Not covered, because backtesting.py does not model them: dividends, settlement, regulatory fees, the volume cap, stops, several instruments or sleeves. backtesting.py is AGPL-3.0, so it is a dev dependency only, and a new import contract fails CI if Tyche imports it.

- Example strategies (PR 18): `trend_rotation` and `mean_reversion` ([ADR-0027](docs/adr/0027-example-strategies-fixed-in-advance.md)), with shared indicators in `tyche.strategies.indicators`. Their rules and parameters were agreed before any backtest and are not to be tuned on results. New workspaces list nine candidate ETFs and ship both strategy files without a budget. Checked end to end: stops placed after their entries fill and hit by the simulator; the rotation opens and closes positions only at the open after a month's first session. On real data, 2005 to 2023, USD 10,000, each alone: the rotation 5.97% a year (max drawdown 29.7%), the mean reversion 1.28% a year (10% exposure, 41 of 328 trades closed by the stop), against 9.59% for SPY's total return. Neither beats the benchmark.

- Backtest report (PR 19, in review): `tyche backtest` writes `report.html` beside each measured run's record, and `tyche report <run id>` rebuilds it from the record alone ([ADR-0028](docs/adr/0028-backtest-report-html-and-cost-drag.md)). One offline HTML file, deterministic, about 300 to 400 KB, with matplotlib charts: summary and equity against the benchmark, drawdown, year by year, trading and exposure, cost drag, what ran, and the data with the limits every result shares. The cost drag counts slippage, which the terminal summary does not: on PR 18's real-data runs, slippage cost each example strategy more than twice its commissions, and the mean reversion's costs were 48% of its profit before costs.

What is missing before judging a strategy: out-of-sample testing (PRs 20 and 21). Packages still holding only a docstring: `core.improvement`, `core.agents`, `core.pipeline.reconciliation`, and the broker, notifier, LLM and storage adapters.

## Decisions from the Phase 0 review (2026-11-16)

| Topic | Outcome |
|---|---|
| ADRs 0003, 0004, 0010, 0011, 0012, 0013 | Accepted as written. All [15 ADRs](docs/adr/README.md) are now accepted. |
| Daily loss limit | Close to close, including stop-outs and fees ([ADR-0015](docs/adr/0015-daily-loss-limit.md)) |
| Small-account costs | Phase 1 adds a cost-drag section to reports and a minimum viable capital analysis (PRs 19 and 22) |
| Paper trading | Phase 2 proposes revised promotion criteria: edge from out-of-sample backtests, paper trading judged by a tracking threshold |
| Overfitting | Trial count, untouched holdout and a deflated Sharpe ratio or equivalent (PRs 15 and 21, then the Phase 3 gate) |
| Settlement | Verify the cash-account rule and model it in `SimBroker` (PRs 9 and 10) |
| Licence | All rights reserved for now |

## Phase 1 plan: core and backtesting (`US`, end of day)

Twenty-three small PRs in six groups. Each PR includes its tests and docs, and a learning note when it introduces a pattern. A dependency is added in the PR that first uses it. Nothing here costs money.

**A. Foundations**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 1 | Domain types (**merged**) | `Currency`, `Money`, `Instrument`, `Timeframe`, `Bar` | |
| 2 | Event envelope and bus (**merged**) | Envelope fields, FIFO bus, run to completion, fail closed, an event-log helper for tests | |
| 3 | Clock and calendar (**merged**) | `Clock` and `Calendar` ports, `Session`, `SimClock`, NYSE calendar adapter. `SessionEvent` moves to PR 7, where the engine first publishes it | Adds `exchange_calendars` (Apache-2.0, free). |
| 4 | Workspace and config (**merged**) | `TYCHE_HOME`, `tyche init`, typed config for the `US` profile, config hash | Adds `pydantic` and Typer. Decided 2026-11-17: Typer for the CLI; workspace at `~/tyche-workspace` |

**B. Data**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 5 | Data port and Parquet cache (**merged**) | `DataProvider` port, cache that records when data was fetched, quality checks, gap detection against the calendar | Adds `pyarrow` only; pandas waits until code imports it |
| 6a | Dividends, splits and price adjustment (**merged**) | `PriceAdjustment`, `CashDistribution`, `Split`; cached with the bars; full refetch on a new split | Decided: split-adjusted prices, dividends as cash (ADR-0019) |
| 6b | yfinance source (**merged**, via #9) | Daily bars and corporate actions with retries, `tyche data fetch` | Adds `yfinance`. Verified 2026-11-17: Apache-2.0; Yahoo data is for personal use only; `raise_errors` is deprecated in 1.8 |

**C. Engine and simulation**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 7 | Engine and replay feed (**merged**) | The run loop, historical replay (`BarEvent`, `DataReadyEvent`), in-memory journal | Also `SessionEvent` (moved from PR 3), `DataQualityEvent`, `RunEvent`, and the `PacedClock` port |
| 8 | Account ledger (**merged**) | `Order`, `Fill`, `Position`, account with settled and unsettled cash per currency | `AccountEvent` moves to PR 10, where it is first published. Adds `hypothesis` |
| 9 | Costs and settlement (**merged**) | A written, dated summary of IBKR Canada's rules, then commission and slippage models and the share-size rule | Verified 2026-11-17 ([summary](docs/developer-guide/ibkr-canada-costs-and-settlement.md)). [ADR-0020](docs/adr/0020-cost-and-settlement-model.md) accepted 2026-11-17 |
| 10 | `SimBroker` (**merged**) | Next-open fills, stops against daily bars, rejections, partial fills, settlement | Buys from settled cash only; free-riding violations recorded (ADR-0020). `AccountEvent` moves to PR 14 |

**D. Pipeline, up to the first backtest**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 11 | Universe and screening (**merged**) | Stages 1 and 2 for the `US` profile, with liquidity, price and data-quality filters | The rules live in a new `[universe]` table of `config/markets/US.toml`. The universe keeps its own last few bars from `BarEvent`s; PR 12 may replace that with whatever it decides for strategies |
| 12 | Strategy interface and benchmark (**merged**) | The plugin contract, the signals stage, buy-and-hold | Decided 2026-11-18: the window is handed in ([ADR-0021](docs/adr/0021-strategies-see-a-window-handed-in.md)), with positions in the context, rebuild-not-restate for splits, one warm-up path, no partial windows, windows keyed by instrument and timeframe |
| 13 | Portfolio construction (**merged**) | Several strategies at once, per-strategy budgets, conflict resolution | Decided 2026-11-18 ([ADR-0022](docs/adr/0022-portfolio-targets-as-weights-in-sleeves.md)): targets in weights of equity, sized in shares by execution; one sleeve per strategy; each contribution keeps its own stop; one PR with strategy config. Splitting a netted fill between sleeves moves to PR 14, where fills arrive |
| 14 | Risk gate (pass-through) and execution (**merged**) | `ApprovedPortfolioEvent` with no rules yet, target-to-order diffing, idempotent order ids | Decided 2026-11-19 ([ADR-0023](docs/adr/0023-execution-sleeves-stops-and-cash.md)): one PR, not split; a stop is placed when its entry fills and works from the next session; sleeves cross first, then the rest is netted and fills are split pro rata; a 10% rebalance band; a 2% price buffer on purchases. Also `AccountEvent`, `CancelRequestEvent`, `ExecutionPlanEvent`, the sleeve book, and a `SimBroker` buying-power fix |
| 15 | Backtest runner (**merged**) | `tyche backtest`, a run record with config hash and code version, the reserved holdout | Decided 2026-11-19 ([ADR-0024](docs/adr/0024-backtest-runner-holdout-and-run-record.md)): the holdout starts on a fixed date, 2024-01-01; the candidate instruments are listed in the market profile. Also: cache-only runs, universe warm-up, every run recorded. **Milestone: first end-to-end backtest** (reached) |

**E. Measurement**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 16 | Metrics (**merged**) | CAGR, volatility, Sharpe, Sortino, max drawdown, turnover, win rate, exposure, all against the benchmark; golden-file regression test | Decided 2026-11-19 ([ADR-0025](docs/adr/0025-metrics-against-the-benchmarks-total-return.md)): the benchmark is the ETF's total return computed from the cache, not the simulated buy-and-hold; the risk-free rate is zero for now. The benchmark ETF is a new `[benchmark]` table in the market profile |
| 17 | Reference validation (**merged**) | Our backtester compared with an independent library on a simple strategy, kept as a regression test | Decided 2026-11-19 ([ADR-0026](docs/adr/0026-reference-validation-against-backtesting-py.md)): backtesting.py (AGPL-3.0), as a test-only dependency fenced off by an import contract; vectorbt (Apache-2.0 with the Commons Clause, about 60 packages) was the alternative. Licences checked on PyPI and in both repositories |
| 18 | Example strategies (**merged**) | An ETF trend rotation and a mean-reversion strategy that uses a stop | Decided 2026-11-19 ([ADR-0027](docs/adr/0027-example-strategies-fixed-in-advance.md)): nine ETFs across asset classes; monthly, top 3 by 126-session return, each above its 200-session average; RSI(2) below 10 above the 200-session average, exit above the 5-session average, stop 2.5 ATR(14) below the entry close. Fixed before any backtest |
| 19 | Backtest report (**in review**) | HTML or Markdown with charts, a cost-drag section, the data-limits statement | Decided 2026-11-20 ([ADR-0028](docs/adr/0028-backtest-report-html-and-cost-drag.md)): one self-contained HTML file per run, charts by matplotlib (plotly would embed 4.8 MB per report or need internet to open); cost drag by adding costs back onto equity from the record, not by a second simulation |

**F. Out-of-sample testing and honest answers**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 20 | Train/test and walk-forward | In-sample and out-of-sample results reported separately | |
| 21 | Parameter sweeps | Sweeps with a trial count, a deflated Sharpe ratio and overfitting warnings | |
| 22 | Minimum viable capital | For each strategy, the account size at which its edge survives costs; proposed defaults if under $1,000 CAD with five positions does not work | |
| 23 | Phase 1 wrap-up | User guide (installation, running a backtest), developer guide pages, version 0.1.0 | Stop for Phase 1 review |

Two things in the brief's Phase 1 that this plan moves:

- **Risk-profile sweeps** wait for Phase 2, because risk profiles do not exist until the risk layer is built. Phase 1 has a pass-through gate so that the event flow is already the final one.
- **The holdout** arrives with the first backtest (PR 15), earlier than the improvement loop that needs it, so that no Phase 1 experiment uses it up.

## Carried into later phases

| Commitment | Phase |
|---|---|
| Risk-profile sweeps and side-by-side profile comparison | 2 |
| Paper and live rebuild the signals windows from the cache at every start and after a split refetch, through `SignalsStage.warm_up` (ADR-0021) | 2 |
| Revised promotion criteria with a paper-versus-backtest tracking threshold, as an ADR for approval | 2 |
| User guide page on what protects a position within a session ([ADR-0015](docs/adr/0015-daily-loss-limit.md)) | 2 |
| Maintenance runbook: update `exchange_calendars` regularly, because unscheduled market closures only appear after a library update | 2 |
| ~~Simulated broker credits distributions as cash at the ex-date, and documents that rule (ADR-0019)~~ Done in PR 10: [backtesting internals](docs/developer-guide/backtesting-internals.md) | 1 (PR 10) |
| Withholding tax on US dividends paid to a Canadian resident: verify the rate and IBKR's handling, then model it | 2 or 4 |
| Trial registry, holdout and deflated results inside the automated gate | 3 |
| Paper and live keep the sleeve book across restarts (stored, or rebuilt from fills) and reconcile it with the broker's positions; execution places a stop only after the broker reports the entry's fill (ADR-0023) | 2 |
| A day order still open at the next decision (possible live, impossible in the simulator) currently halts the run; decide how live execution handles it | 2 |
| Paper and live fetch exactly the candidate list in the market profile (ADR-0024); `tyche data fetch` could fetch the whole list in one command | 2 |
| `starting_cash` is in the profile's first cash currency; `CA+US` needs cash per currency | 4 |
| The Phase 3 promotion check is the one code path allowed to read the holdout, and records that it did (ADR-0024) | 3 |
| Interest on cash in the simulator, and a real risk-free rate (such as T-bills) for Sharpe and Sortino, in one change (ADR-0025) | 2 or later |
| ~~A command to measure an existing record from its `equity.csv` and `fills.csv`, if the report needs it~~ Not needed: the report reads `metrics.json` (ADR-0028) | 1 (PR 19) |

## Open decisions

| Decision | Needed by |
|---|---|
| Turn on branch protection for `main` (require a PR and the CI check); a GitHub setting only you can change | Now, recommended |
| Whether to add "never move `holdout_starts` later" to the never-do rules in `CLAUDE.md`. The code cannot stop an edit to your own config file; the rules are yours to change | Open since PR 15's review |
| Opening an IBKR account and its paper account, if not done yet; approval can take days | Before Phase 2 |
| Scheduler: APScheduler or cron in the container | Phase 2 |
| SQLite migration approach | Phase 2 |

Decisions that belong to a Phase 1 PR are listed in the plan above.

## To verify against current sources (not from memory)

| Fact | Where |
|---|---|
| ~~IBKR Canada commissions, minimums and fractional-share rules~~ Done 2026-11-17: Fixed USD 0.005 a share, min USD 1.00, max 1%; no fractional orders through the API | Phase 1, PR 9 |
| ~~Settlement rules for an IBKR Canada cash account~~ Done 2026-11-17: T+1, settled cash only, free-riding rule | Phase 1, PR 9 |
| Whether an IBKR Canada cash account can spend unsettled proceeds (IBKR's pages disagree), and when on the settlement date proceeds count as settled | Phase 2, paper account |
| Whether GST or PST applies to stock commissions for a Canadian resident | Phase 2, first statement |
| FINRA Trading Activity Fee rate after its holiday ends on 2026-12-31 | Before Phase 2 |
| ~~yfinance limits, terms and adjusted-price behaviour~~ Done 2026-11-17: personal use only, no documented rate limit, "unadjusted" prices are split-adjusted (ADR-0019) | Phase 1, PR 6 |
| ~~Licences of the candidate reference backtesters~~ Done 2026-11-19: backtesting.py 0.6.6 AGPL-3.0; vectorbt 1.2.1 Apache-2.0 with the Commons Clause | Phase 1, PR 17 |
| Linux wheels for all dependencies on Python 3.14 (Docker) | Phase 2 |
| IB Gateway ports, account-id formats, IBC behaviour, 2FA flow | Phase 2 |
| `claude -p` flags, output format and plan limits | Phase 3 |

## Known issues and risks

The honest notes, with what was agreed for each, are in the [system overview, section 9](docs/architecture/system-overview.md#9-assumptions-and-honest-notes).

## Next

1. Pablo reviews and merges PR 19. Worth a look in [ADR-0028](docs/adr/0028-backtest-report-html-and-cost-drag.md): "Implementation choices made in PR 19, for review there" (built from the record alone, the three layers, lines drawn as images inside the SVG to keep reports small, a failed report not failing the backtest).
2. **Your workspace needs no change for PR 19.** Each new backtest writes its report; `tyche report <run id>` writes one for a run recorded earlier. Reports add about 300 to 400 KB per run to your workspace repository. If not done yet, PR 16's `[benchmark]` table is still needed; earlier notes still apply to older workspaces (`[backtest]` and `instruments` before PR 15, `[execution]` before PR 14, `[strategies]` before PR 13, `[universe]` before PR 11, `config/costs/US.toml` before PR 9).
3. Phase 1, PR 20: train/test and walk-forward, with in-sample and out-of-sample results reported separately, when Pablo says to start it.

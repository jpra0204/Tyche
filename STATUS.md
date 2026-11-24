# Status

*Last updated: 2026-11-23*

## Current phase

**Phase 2: risk and paper trading (`US`, end of day). Pablo agreed the PR list below on 2026-11-23.**

- PR 1 (guardrails and named risk profiles) is merged (#30); [ADR-0032](docs/adr/0032-risk-limits-in-three-layers.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23: a guardrail ceiling for every profile limit; money caps per cash currency until Phase 4; strategies may tighten position rules only. `--risk-profile` on the backtest commands moves to PR 2, where it first changes a result.
- PR 2 (the risk gate's position rules) is merged (#33); [ADR-0033](docs/adr/0033-risk-gate-position-rules.md) accepted on 2026-11-23.
- PR 3 (order-level guardrails) is merged (#35, re-landed on `main` through #36 because #35 merged into #34's branch); [ADR-0034](docs/adr/0034-order-level-guardrails.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: with money caps, size as if equity were the capital cap; a purchase over a cap shrinks to the whole shares that fit.
- PR 4 (the daily loss limit and the drawdown kill) is merged (#37); [ADR-0035](docs/adr/0035-account-rules-and-the-drawdown-halt.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: a backtest halted by the drawdown kill runs on to its last day with no orders, holding what it held, as an account nobody restarted would.
- PR 5 (risk profiles side by side) is merged (#39); [ADR-0036](docs/adr/0036-risk-profiles-side-by-side.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: a comparison adds no trial and names no best profile, with a warning; one small-account profile per live stage (`stage-1` 1 position up to 100%, `stage-2` 2 up to 50%, `stage-3` 4 up to 25%); documented in the user guide, not shipped in the template.
- PR 6 (SQLite state store and a durable journal) is merged (#41); [ADR-0037](docs/adr/0037-state-database-migrations-and-stored-journal.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: numbered SQL migrations versioned by `user_version`, no new dependency. Accepted with the ADR: events stored as tagged JSON with a format number; one commit per envelope with the stored journal subscribed first; only paper and live write to it, backtests keep the in-memory journal.
- PR 7 (state across restarts) is merged (#43); [ADR-0038](docs/adr/0038-checkpoints-across-restarts.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: **a checkpoint saved at the end of every run**, not a replay of the journal (the question carried from ADR-0023). Accepted with the ADR: one append-only row per run in the state database, tied to that run's stored journal; a failed run saves none; the halt comes back with it; latest closes are not saved.
- PR 8 (kill switch) is merged (#45); [ADR-0039](docs/adr/0039-kill-switch-and-manual-restart.md) accepted on 2026-11-23. Decided with Pablo on 2026-11-23, before any code: **a flatten cancels each resting stop, then sells** at the next open; **an order already working at the broker is left to fill or expire**, listed by `tyche kill` for him to cancel in IBKR's app if he wants (the CLI never reaches the broker); **`tyche resume` forgets the peak**, so the drawdown kill counts from the first close after it. Accepted with the ADR: the flag file's place and format, carrying the switch on `ApprovedPortfolioEvent` instead of the planned `HaltEvent`, and recording a resume as a run of its own with a new checkpoint.
- PR 9 (logs, secrets and the Discord notifier) is **in review**; [ADR-0040](docs/adr/0040-logs-secrets-and-alerts.md) is *Proposed*. Decided with Pablo on 2026-11-23, before any code: **the standard library reads `.env`**, not `pydantic-settings`; **`tyche kill` and `tyche resume` post now, runs from PR 14**, backtests never; the daily loss limit and the drawdown kill are alerts, routine position-size and money-cap cuts are not. In the ADR, for acceptance: alerts collected during a run and sent after it, never from a bus handler; `urllib`, no HTTP library; plain text, nobody mentioned; a lost alert is logged, not retried.

**Phase 1 is done.** All 23 PRs are merged (the last, #28, on 2026-11-23), every ADR up to 0031 is accepted, and the version is 0.1.0. Its PR list and decisions are kept below for reference.

<details>
<summary>Phase 1, PR by PR</summary>


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
- PR 19 (backtest report) is merged; ADR-0028 accepted.
- PR 20 (walk-forward) is merged; ADR-0029 accepted.
- PR 21 (parameter sweeps) is merged; ADR-0030 accepted: every distinct trial ever recorded for a plugin is counted, the pick is the highest Sharpe ratio, it is reported with a deflated Sharpe ratio, and a sweep keeps one table of trials plus the pick's full record. One PR, not split.
- Fix: the data cache now covers sessions before an instrument's first bar when the source has nothing for them, so the fetch hint for GLD and VNQ no longer loops. Merged (#25); no workspace change needed, and no need to delete cache files.
- PR 22 (minimum viable capital) is merged; ADR-0031 accepted on 2026-11-23 (its proposed small-account defaults stay open, below). Decided with Pablo on 2026-11-22 and 23: the size penalty against a large reference account (within half a point a year, either way), a latest-close check of today's share prices (the one read of a holdout bar), capital varied but not positions, and a USD 100,000 reference after USD 1,000,000 proved too large for the rotation.
- PR 23 (Phase 1 wrap-up) is merged (#28): version 0.1.0; every user-guide command re-run in a fresh workspace; new pages for pipeline contracts and troubleshooting.
- Adjusted prices decided 2026-11-17: split-adjusted prices with dividends as cash events ([ADR-0019](docs/adr/0019-split-adjusted-prices-and-cash-dividends.md)).

</details>

Recommended, still: turn on *Automatically delete head branches* in the GitHub repository settings, so GitHub retargets stacked PRs by itself.

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

- Backtest report (PR 19): `tyche backtest` writes `report.html` beside each measured run's record, and `tyche report <run id>` rebuilds it from the record alone ([ADR-0028](docs/adr/0028-backtest-report-html-and-cost-drag.md)). One offline HTML file, deterministic, about 300 to 400 KB, with matplotlib charts: summary and equity against the benchmark, drawdown, year by year, trading and exposure, cost drag, what ran, and the data with the limits every result shares. The cost drag counts slippage, which the terminal summary does not: on PR 18's real-data runs, slippage cost each example strategy more than twice its commissions, and the mean reversion's costs were 48% of its profit before costs.

- Walk-forward (PR 20): `tyche walk-forward --from <date>` cuts history into folds of calendar years, runs each training and test window as a backtest of its own from the starting cash, and reports in-sample and out-of-sample results side by side, with the test windows joined into one out-of-sample result against the benchmark joined the same way ([ADR-0029](docs/adr/0029-walk-forward-folds-and-a-train-step.md)). Defaults: anchored, a five-year first training window, one-year test windows, so 14 folds testing 2010 to 2023; `--rolling`, `--train-years` and `--test-years` change them. Between each fold's two runs a train step decides what the test window runs; until PR 21 it keeps the configured parameters, so the in-sample/out-of-sample gap shows how results vary by period, not overfitting, and the report says so first. Each walk-forward writes `reports/walk_forward/<id>/` with every window's full backtest record and one `report.html`; `tyche report <id>` rebuilds it. Checked on real data, testing 2010 to 2023: buy-and-hold 12.14% a year against the benchmark's 12.58%, the rotation 4.57% (ahead in 2 of 14 test years), the mean reversion 1.25%. The rotation's in-sample lead on 2005 to 2009 (11 points a year, mostly 2007 and 2008) did not carry into any later fold. Each run takes 2 to 3 minutes and writes about 7 MB.

- Parameter sweeps (PR 21): `tyche sweep <name> --from <date>` runs every combination of `config/sweeps/<name>.toml` as a backtest over the same days, picks the highest Sharpe ratio, and reports it with a deflated Sharpe ratio and overfitting warnings ([ADR-0030](docs/adr/0030-parameter-sweeps-trial-count-and-deflated-sharpe.md)). The trial count is every distinct trial of the plugin ever recorded in the workspace. `tyche walk-forward --sweep <name>` picks on each training window. A sweep keeps `trials.json` and the pick's full record (968 KB for the example's 27 trials). Checked on real data, 2005 to 2023: the example sweep's pick (4 holdings, 252-session momentum) has a Sharpe ratio of 0.71 against SPY's 0.57 and a CAGR of 8.28% against 9.59%, with a deflated Sharpe ratio of 98.2% after 27 trials and two parameters at the edge of the grid. SPY itself scores 99.3% on the same test, so the deflated Sharpe ratio filters out luck but is no verdict against the benchmark. The walk-forward with the same sweep settles it: out of sample, 2010 to 2023, the yearly picks earned 4.29% a year with a Sharpe ratio of 0.42, no better than the configured parameters (4.57%, 0.42) and against SPY's 12.58% and 0.77, although 13 of the 14 training picks were significant at 95%. The picks changed between seven combinations across the folds. The run took about 2 hours 20 minutes.

- Minimum viable capital (PR 22): `tyche capital --from <date>` runs each configured strategy alone at several account sizes and on a USD 100,000 reference account, under IBKR Pro Fixed and Tiered (new optional `[tiered]` table in the costs file), and reports the smallest amount from which every larger one is within half a point a year of the reference, beside whether the strategy beats SPY ([ADR-0031](docs/adr/0031-minimum-viable-capital.md)). Also the cost of one round trip per position, and the whole shares one of five positions buys at each candidate's latest close. On real data, 2005 to 2023: buy-and-hold viable from USD 700, the mean reversion from USD 10,000 (Fixed) or 5,000 (Tiered) with no edge at any size, the rotation from USD 25,000 under both plans. **Five positions under CAD 1,000 does not work**: about USD 140 a position, 2.12% a round trip under Fixed (0.84% Tiered), and SPY, QQQ, GLD and IWM cost more than one position today. Tiered cut small-account costs by a half to two thirds. Proposed defaults, for Pablo: Tiered, one or two positions below about USD 5,000, low turnover below USD 10,000.

- Risk limits (Phase 2, PR 1): `config/guardrails.toml` (long only, no leverage, a ceiling for every profile limit, capital and order caps per cash currency), named risk profiles in `config/risk/` (`default` ships with the brief's values) and an optional `[risk]` table per strategy, each layer checked against the one above when Tyche starts, every breach named with its file, key, value and limit ([ADR-0032](docs/adr/0032-risk-limits-in-three-layers.md)). `tyche config check --risk-profile <name>` checks against a chosen profile.

- Risk gate, position rules (Phase 2, PR 2): `RiskGate` replaces the pass-through gate and applies the active profile's, and each strategy's own, risk per trade (entries and additions with a stop, at the decision's close, never trimming a holding), max open positions (held positions keep their place, new entries fill free places largest first) and max position size (at every close; several sleeves in one instrument shrink in proportion). It only lowers or removes contributions; every cut is a `RiskEvent` and is listed on the `ApprovedPortfolioEvent` ([ADR-0033](docs/adr/0033-risk-gate-position-rules.md), accepted 2026-11-23). `--risk-profile` on every backtest command (default `default`), recorded in `run.json` with the cuts counted by rule. Property-based tests check that no proposal yields an approved portfolio past a limit. On real data, 2005 to 2023, USD 10,000: under `default`, buy-and-hold SPY ends at 14,568 USD (was 52,168; max drawdown 13% instead of 53%), the rotation at 23,464 (was 30,049), the mean reversion at 10,650 (was 12,735; its costs now exceed its gain). Under a profile that does not bind, all three reproduce their earlier results to the cent. The daily loss limit and the drawdown kill came in PR 4, below.

- Order-level guardrails (Phase 2, PR 3): execution checks long only (sales and resting stops never exceed what the account holds) and no leverage (purchases within the buying power) at every decision of every run, and halts on a breach. Given the guardrails' money caps, as paper and live will be (research backtests are not), it sizes weights on the lower of equity and `max_total_capital`, and cuts each purchase to fit `max_order_value` and what is left under `max_total_capital`, each cut a `RiskEvent` ([ADR-0034](docs/adr/0034-order-level-guardrails.md), accepted 2026-11-23). `ExecutionPlanEvent.sized_on` records the equity sized on; `run.json` records which caps applied. Research backtests are unchanged. A property-based test checks that no purchase exceeds either cap.

- Account rules (Phase 2, PR 4): the gate measures equity at every close (`AccountRules`). A loss of at least `daily_loss_limit` since the previous close blocks every entry and addition at that close; exits and reductions go through. A fall of at least `drawdown_kill` below the highest close halts trading for the rest of the run: the gate approves nothing and carries the halt on `ApprovedPortfolioEvent.halt`, execution keeps every holding and sends no order (plan note `halted`), and stops already resting stay. A halted backtest runs on to its last day. Each trigger is a `RiskEvent` with an `AccountTrigger`; `run.json` gains `outcome.account_rules`; the summary has an `Account rules:` line; the report warns of a halt and marks it on its charts ([ADR-0035](docs/adr/0035-account-rules-and-the-drawdown-halt.md), accepted 2026-11-23). A property-based test checks that after a losing session no approved contribution exceeds what its sleeve holds. On real data, 2005 to 2023, USD 10,000, under `default`: buy-and-hold and the mean reversion trigger neither rule and are unchanged; the trend rotation hits the daily loss limit three times and halts on 2020-03-18, 15.11% below its peak. Holding its three funds untouched from then on, it ends at 25,915 USD (was 23,464) with a worst fall of 20% (was 15%), which is luck after the halt, not evidence about the strategy. Kept across restarts since PR 7; lifted by hand with `tyche resume` since PR 8.

- Risk profiles side by side (Phase 2, PR 5): `tyche compare-profiles --from <date> [--risk-profile <name>]...` runs the configured strategies once per profile (every profile in `config/risk/` by default) over the same days, and writes `reports/profiles/<id>/` with `profiles.json`, each profile's full record under `runs/<profile>/`, and a report: one table and one equity and drawdown chart for every profile against the benchmark, each halt marked with the share of the range still to run, and what each profile's limits did. It names no best profile and adds no trial; the report warns that choosing on its results is a selection ([ADR-0036](docs/adr/0036-risk-profiles-side-by-side.md), accepted 2026-11-23). Sweep trials and capital runs now record `halted_at`, and the sweep, walk-forward and capital reports warn of every halted run. The user guide gives one profile per live stage (`stage-1`, `stage-2`, `stage-3`) to create in your workspace. On real data, the example rotation alone, 2005 to 2023, USD 10,000: `default` 5.14% CAGR, halted 2020-03-18; `stage-1` 2.71%, never halted, but only a third invested, because **a profile only lowers what a strategy asks for** and the rotation asks for a third in each of three funds; `stage-2` 4.59% and `stage-3` 4.15%, both halted on 2006-06-13 with 92% of the range still to run. At USD 700 `stage-2` halted on the same day and the others ran 1.2% to 1.6% a year.

- State database and a durable journal (Phase 2, PR 6): `open_database` opens `state/tyche.db` with foreign keys, write-ahead logging and `synchronous = FULL`, and applies numbered SQL migrations in one transaction each, versioned by `user_version`; it refuses a file from a later Tyche. The journal table is append-only (triggers refuse updates and deletes), keyed by run and `seq`, with each cause a foreign key. `StoredJournal` writes every envelope through the `JournalStore` port, committed before the next handler runs; a refusal halts the bus. Events are stored as tagged JSON for a closed list of Tyche's own types and read back identical: checked on every event of two real backtests and on samples of the rare ones ([ADR-0037](docs/adr/0037-state-database-migrations-and-stored-journal.md), accepted 2026-11-23). **Not yet:** nothing writes to it; the paper cycle will (PR 14).

- State across restarts (Phase 2, PR 7): every completed run ends in a `Checkpoint` (Tyche's account view, the sleeve book with resting stops, execution's working orders with what each owes each sleeve and the stops sleeves want, and the account rules' previous close, peak and halt), checked on construction so that parts that disagree are refused. Each stage exports its part (`.state()`) and is built from it (`start=`, `rules=`); the universe and the signals are warmed up from the cache as before. `SqliteCheckpointStore` (migration `0002_checkpoint.sql`) keeps one append-only row per run, tied to that run's stored journal, through the `CheckpointStore` port ([ADR-0038](docs/adr/0038-checkpoints-across-restarts.md), accepted 2026-11-23). `run_backtest(..., resume=)` carries a backtest on from a checkpoint, with `SimBroker.state` and `SimBroker.resume` standing in for the broker's own memory. Tested: two years of three sleeves on four instruments, cut in two at awkward moments (market orders working, stops resting in two sleeves, month ends, either side of a drawdown halt, and through the SQLite store), publish the same fills, closes, plans, approvals, orders and risk events and end in the same state as one run straight through. **Not yet:** the paper cycle that loads and saves it (PR 14).

- Kill switch (Phase 2, PR 8): the `KILL` file at the workspace root, read by the risk gate at every decision through the `KillSwitch` port (`FlagFileKillSwitch`). While it is there, the gate approves nothing and carries the `Kill` on `ApprovedPortfolioEvent.kill`. Without flatten, execution keeps every holding and sends nothing (plan note `killed`); resting stops stay. With flatten, it cancels every stop, then sells every holding of every sleeve at the next open, and buys nothing (`flattened`). An empty or unreadable file engages it without flatten. `tyche kill [--reason] [--flatten]` writes the flag, never weakens one already there, and lists the orders the latest checkpoint left working and any halt. `tyche resume --reason` asks, then journals a `ResumeEvent` as a run of its own and, under a drawdown halt, saves a checkpoint with the halt lifted and the peak forgotten (`AccountRulesState.resumed`), and removes the flag last ([ADR-0039](docs/adr/0039-kill-switch-and-manual-restart.md), accepted 2026-11-23). Backtest commands read no switch; `run_backtest(..., kill_switch=)` lets tests script one. Tested over two years of three sleeves: engaged without flatten, nothing is submitted again; with flatten, every stop is cancelled before the sales and the run ends in cash with no order working; released, it trades again; a halt resumed by hand trades again with the peak counted from the restart. Runbook: [`kill-switch.md`](docs/runbooks/kill-switch.md). **Not yet:** the paper cycle that reads it (PR 14); a lock against running either command during a cycle (PR 15).

- Logs, secrets and Discord alerts (Phase 2, PR 9, [ADR-0040](docs/adr/0040-logs-secrets-and-alerts.md), proposed): every command run on a workspace logs JSON lines to `logs/<UTC date>.jsonl`, private, with every `.env` secret and any Discord webhook URL redacted. `.env` is read with the standard library in a strict format (known keys only, the environment winning), as `SecretStr`s; `tyche config check` reports the webhook and warns about a readable `.env`. The `Notifier` port and `DiscordWebhookNotifier` (`urllib`, `?wait=true`, no mentions, Discord's rate-limit headers and `retry_after`, a refused webhook retired). `AlertCollector` turns account triggers, the kill switch and data problems into alerts for the paper run to send after it ends (PR 14). `tyche kill` and `tyche resume` post at once; `tyche notify test` checks the channel. A Discord failure never fails a command. Discord's limits checked on 2026-11-23. Checked end to end in a scratch workspace; the real `urllib` path reached Discord once, with a made-up webhook, and handled its 404.

Packages still holding only a docstring: `core.improvement`, `core.agents`, `core.pipeline.reconciliation`, and the broker, notifier and LLM adapters.

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

## Phase 2 plan: risk and paper trading (`US`, end of day)

*Agreed by Pablo on 2026-11-23, with the three moves listed after the tables.* Twenty small PRs in five groups. Each PR includes its tests and docs, and a learning note when it introduces a pattern. A dependency is added in the PR that first uses it. The brief's Phase 2: the risk layer with named profiles and guardrails, profile comparison in backtests, the IBKR paper adapter, execution, reconciliation, the scheduler, the catch-up rule, the journal, the Discord webhook, the kill switch, Docker, and a user guide for running in paper.

**Order.** Groups A and B need no broker account: the risk layer is pure core code, tested in backtests, and the running state and operations come next. That leaves time for the IBKR account and its paper account to be approved before group C needs them (PR 10).

**Cost.** Nothing in this plan is meant to cost money. Three things are checked before they are added, and flagged in their PR if they are not free: the IBKR paper account (PR 10), the IB Gateway image and Docker on your Mac (PR 18), and market data. Paper decisions use the same free Yahoo daily bars as backtests; IBKR market data stays off, because it may need paid subscriptions (brief §4.5).

**A. Risk layer (backtests only)**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 1 | Guardrails and named risk profiles (**merged**) | `config/guardrails.toml`, `config/risk/<name>.toml` and per-strategy overrides, checked at startup in [ADR-0010](docs/adr/0010-config-toml-pydantic.md)'s order, each violation naming the file, key, value and limit. `tyche init` ships the `default` profile of brief §7.1; `tyche config check --risk-profile` prints the active profile | Decided 2026-11-23 ([ADR-0032](docs/adr/0032-risk-limits-in-three-layers.md), accepted 2026-11-23): a guardrail ceiling for every profile limit; money caps per cash currency, no exchange rate; a strategy's `[risk]` table may tighten risk per trade, position size and its own position count only. Every profile checked, only the active one hashed. `--risk-profile` on the backtest commands moved to PR 2 |
| 2 | Risk gate: position rules (**merged**) | `--risk-profile` on every backtest command, recorded in the run record (moved from PR 1). `RiskGate` replaces `PassThroughGate`: risk-per-trade sizing for targets with a stop ([ADR-0006](docs/adr/0006-target-positions-with-optional-stops.md)), max position size, max open positions. `RiskEvent`, and `adjustments` on `ApprovedPortfolioEvent`. Property-based tests: no input yields an approved portfolio that breaks the profile or the guardrails | Decided 2026-11-23, before any code: (1) above max open positions, held positions keep their place and new entries fill the free places, largest target weight first, ties by symbol; every blocked entry recorded. (2) An instrument above max position size: every sleeve's contribution shrinks by the same proportion, each stop still sized to its own sleeve's shares. (3) Max position size applies at every cycle, to what is held too (the rebalance band prevents churn); risk per trade only on entries and additions, because with a fixed stop it would trim every winner. (4) A backtest without `--risk-profile` uses `default`; buy-and-hold then holds 20% SPY and the rotation at most 60%, and the PR documents it and reruns the examples under it. Also in the PR: risk per trade sized at the decision's close; a `RiskEvent` for every cut or block; the golden-file and reference tests run under a test profile that leaves their trades unchanged. An ADR records it |
| 3 | Order-level guardrails (**merged**) | A last check in execution that every order is within the guardrails (long only, no leverage, max order value, capital cap), because orders are only sized in shares after the gate | Decided 2026-11-23 ([ADR-0034](docs/adr/0034-order-level-guardrails.md), accepted 2026-11-23): with money caps, weights are sized on the lower of equity and the capital cap (money above it, gains included, stays in cash until Pablo raises the cap); a purchase over a cap shrinks to the whole shares that fit, refused only when not one fits; sales are never cut; a short or a purchase on credit halts the run as a bug. Also agreed: the money caps describe the real account, so they bind in paper and live; research backtests keep their `starting_cash` and apply only the percentage limits, and `tyche capital` checks a strategy at the account sizes Pablo plans to trade |
| 4 | Daily loss limit and drawdown kill switch (**merged**) | [ADR-0015](docs/adr/0015-daily-loss-limit.md)'s close-to-close limit (no new entries or additions after a losing session); peak equity tracked by the risk layer; a drawdown halt that only a manual restart lifts; a `RiskEvent` for every trigger | Decided 2026-11-23 ([ADR-0035](docs/adr/0035-account-rules-and-the-drawdown-halt.md), accepted 2026-11-23): a halted backtest runs on to its last day with no orders, holding what it held; its metrics cover the whole range. The report warns at the top and marks the halt on the equity and drawdown charts; the record and the summary say when and how far |
| 5 | Risk profiles side by side (**merged**) | The same strategies under several profiles over the same days, reported side by side in one report: the brief's risk-profile sweeps. Shows which runs the drawdown kill halted, and when (carried from PR 4) | Decided 2026-11-23 ([ADR-0036](docs/adr/0036-risk-profiles-side-by-side.md), accepted 2026-11-23): no trials added, no pick, a warning instead; one profile per live stage, in the user guide, not the template. Was: decide whether a profile comparison counts towards the plugin's trial count ([ADR-0030](docs/adr/0030-parameter-sweeps-trial-count-and-deflated-sharpe.md)); and the small-account profile from [ADR-0031](docs/adr/0031-minimum-viable-capital.md)'s proposed defaults, which is yours to decide. It must be able to trade within your workspace's guardrails at the first live stage, where `default` (five positions of 20%) cannot |

**B. Running state and operations (no broker yet)**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 6 | SQLite state store and a durable journal (**merged**) | A storage port and a SQLite adapter (standard-library `sqlite3`); the append-only journal of every event with its cause ([ADR-0009](docs/adr/0009-storage-sqlite-parquet.md)) | Decided 2026-11-23, before any code: numbered SQL files and SQLite's `user_version`, with no new dependency. Accepted with [ADR-0037](docs/adr/0037-state-database-migrations-and-stored-journal.md) on 2026-11-23: events as tagged JSON with a format number, one commit per envelope, paper and live only |
| 7 | State across restarts (**merged**) | Orders, fills, the sleeve book, Tyche's account view, peak equity and the halt state saved and reloaded, so a restart carries on where the last run stopped; signals windows rebuilt from the cache through `SignalsStage.warm_up` ([ADR-0021](docs/adr/0021-strategies-see-a-window-handed-in.md)) | Decided 2026-11-23, before any code: a checkpoint at the end of every run, stored whole, not rebuilt from fills (crossings move shares with no fill) nor by replaying the journal ([ADR-0038](docs/adr/0038-checkpoints-across-restarts.md), accepted 2026-11-23). Was carried from [ADR-0023](docs/adr/0023-execution-sleeves-stops-and-cash.md) |
| 8 | Kill switch (**merged**) | The `KILL` flag file plus `tyche kill` and `tyche resume`; read by the gate at every decision; no new orders, optional flatten; `tyche resume` also lifts the drawdown halt. `kill-switch` runbook. Reporting the switch at a paper run's startup moves to PR 14, which builds the first run that reads it | Decided 2026-11-23, before any code ([ADR-0039](docs/adr/0039-kill-switch-and-manual-restart.md), accepted 2026-11-23): a flatten cancels every stop, then sells; working orders are left and listed; resume forgets the peak. Was: whether a flatten cancels resting stops first, and what it does with an order already working |
| 9 | Logs, secrets and the Discord notifier (**in review**) | Structured logs in daily files, with secrets redacted; `.env` and `.env.example`; the `Notifier` port and a Discord webhook adapter; the alerts of brief §9 that exist by then (risk limit, kill switch, data failure, run failed) | Decided 2026-11-23, before any code ([ADR-0040](docs/adr/0040-logs-secrets-and-alerts.md), proposed): the standard library for `.env`; `tyche kill`, `tyche resume` and `tyche notify test` post now, runs from PR 14, backtests never; only account triggers among risk events. Discord's limits verified 2026-11-23: 2,000 characters, rate-limit headers and `retry_after`, never reuse a 404 webhook, a `DiscordBot` User-Agent. Was: verify Discord's limits; decide `pydantic-settings` or the standard library |

**C. IBKR paper (needs the paper account)**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 10 | IBKR facts, written and dated | A developer-guide page like Phase 1's [costs and settlement](docs/developer-guide/ibkr-canada-costs-and-settlement.md), and an ADR; no code. `ib_async` version and licence; IB Gateway ports; paper and live account-id formats; how an order sent after the close reaches the next open (market-on-open or a day market order); stops that rest across sessions; order references for idempotency; pacing limits; whether a cash account can spend unsettled proceeds; the FINRA Trading Activity Fee after 2026-12-31 | Everything here from current documentation, then confirmed on the paper account where the documents disagree |
| 11 | `IBKRBroker` (paper) | Adds `ib_async`. Connects, refuses any account but the configured paper one ([ADR-0013](docs/adr/0013-live-trading-gate.md)), places and cancels orders with idempotent references, reads positions, cash, open orders and executions. Tested against a fake; opt-in integration tests on the paper account only | Decide: how a resend after a lost connection is recognised as a duplicate |
| 12 | Daily feed and the catch-up rule | The wall clock in the engine; after the close, the session's bars fetched through the cached provider, audited and published as the replay does; a freshness window: missed sessions are fetched, a signal older than the window is skipped and reported, never traded. Fetches exactly the candidate list ([ADR-0024](docs/adr/0024-backtest-runner-holdout-and-run-record.md)), and `tyche data fetch` gains a whole-list option | Decide: the buffer after the close, and the freshness window |
| 13 | Reconciliation | Pipeline stage 7: at startup and after every run, Tyche's positions, cash and open orders compared with the broker's; any difference halts trading and alerts. `reconciliation-mismatch` runbook | Decide: tolerances, if any (commissions are only known after a fill) |
| 14 | Paper run | `tyche paper run`: one decision cycle on the paper account, end to end. Start, reconcile, warm up, read new fills, place the stops of filled entries (ADR-0023), decide, send orders for the next open, save state, report. **Milestone: the first paper cycle** | An ADR for the paper cycle. Carried: a day order still open at the next decision halts the run today; decide what paper does instead. May split into reading the broker (14a) and deciding (14b) if large |

**D. Running unattended**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 15 | Scheduler | The paper cycle after each session's close plus the buffer; a run that did not happen is reported at the next start; `RunEvent` for skipped runs | Open decision: APScheduler or cron in the container |
| 16 | Daily summary | The Discord summary after every run: trades, positions, P&L against the benchmark, risk status, anything skipped | Layout agreed with you on a real paper day |
| 17 | Gateway supervision | Automated gateway restarts through IBC; a needed login or 2FA detected and alerted. `gateway-reauth` runbook | Verify IBC's licence, current version and how it reports a 2FA wait |
| 18 | Docker | A `Dockerfile` (Python 3.14 through `uv`) and `docker compose` with the gateway; the workspace mounted; `start-stop` and `crash-recovery` runbooks | Verify Linux wheels for every dependency on Python 3.14; Docker Desktop's licence terms for personal use; the gateway image: a third-party image is code that runs with your account's credentials, so we build our own or pin one we have read |

**E. Evidence and wrap-up**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 19 | Paper against backtest | A command that replays a paper period in the simulator with the same config and data, and compares fills, slippage, costs and equity with what paper did; a proposed ADR for revised promotion criteria: the edge shown by out-of-sample backtests, paper judged by a tracking threshold (carried from the Phase 0 review) | The ADR is yours to accept |
| 20 | Phase 2 wrap-up | User guide: the IBKR paper account, the gateway, Discord and `.env`; choosing and comparing risk profiles; the daily routine; reading Discord reports; the kill switch; what protects a position within a session (ADR-0015). `maintenance` runbook (updating `exchange_calendars`). Version 0.2.0 | Stop for the Phase 2 review |

What this plan moves (agreed 2026-11-23):

- **The live gate moves to Phase 3.** `tyche live arm` and the Claude Code rule that denies it to agents go with the strategy lifecycle, because only strategies in the `live` state may run live ([ADR-0013](docs/adr/0013-live-trading-gate.md)) and that state arrives in Phase 3. Phase 2 keeps the account-identity check (PR 11), so paper cannot reach a live account, and nothing in Phase 2 can trade live.
- **Withholding tax on US dividends moves to Phase 4**, with currency conversion and the tax export.
- **Interest on cash and a real risk-free rate** stay out of Phase 2: they change every metric at once and are not needed to run in paper.

## Phase 1 plan: core and backtesting (`US`, end of day)

*Done.* Twenty-three small PRs in six groups. Each PR includes its tests and docs, and a learning note when it introduces a pattern. A dependency is added in the PR that first uses it. Nothing here costs money.

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
| 19 | Backtest report (**merged**) | HTML or Markdown with charts, a cost-drag section, the data-limits statement | Decided 2026-11-20 ([ADR-0028](docs/adr/0028-backtest-report-html-and-cost-drag.md)): one self-contained HTML file per run, charts by matplotlib (plotly would embed 4.8 MB per report or need internet to open); cost drag by adding costs back onto equity from the record, not by a second simulation |

**F. Out-of-sample testing and honest answers**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 20 | Train/test and walk-forward (**merged**) | In-sample and out-of-sample results reported separately | Decided 2026-11-20 ([ADR-0029](docs/adr/0029-walk-forward-folds-and-a-train-step.md)): the walk-forward machinery now, with a train step that keeps the configured parameters until PR 21 plugs in a choice; anchored folds of calendar years by default (5-year first training window, 1-year tests), rolling optional |
| 21 | Parameter sweeps (**merged**) | Sweeps with a trial count, a deflated Sharpe ratio and overfitting warnings | Decided 2026-11-19 ([ADR-0030](docs/adr/0030-parameter-sweeps-trial-count-and-deflated-sharpe.md)): one PR, not split; `N` is every distinct trial of the plugin ever recorded in the workspace; the pick is the highest Sharpe ratio; one `trials.json` per sweep plus the pick's full record; the grid in `config/sweeps/<name>.toml`. A walk-forward with `--sweep` picks on each training window; each combination counts once however many folds run it; the out-of-sample result is not deflated. Deflated Sharpe formula checked against the paper's worked example |
| 22 | Minimum viable capital (**merged**) | For each strategy, the account size at which its edge survives costs; proposed defaults if under $1,000 CAD with five positions does not work | Decided 2026-11-22 and 23 ([ADR-0031](docs/adr/0031-minimum-viable-capital.md), accepted 2026-11-23): the size penalty against a large reference account, within half a point a year either way; each strategy alone with its configured parameters, only the capital varied; Fixed against Tiered with an assumed exchange fee of USD 0.0030 a share (rates re-checked 2026-11-22); today's share prices from the latest cached close, the one read of a holdout bar; a USD 100,000 reference, flagged if the volume cap binds |
| 23 | Phase 1 wrap-up (**merged**) | User guide (installation, running a backtest), developer guide pages, version 0.1.0 | Every user-guide command re-run in a fresh workspace on 2026-11-23; new pages: pipeline contracts (developer guide) and troubleshooting (user guide). Stop for Phase 1 review |

Two things in the brief's Phase 1 that this plan moves:

- **Risk-profile sweeps** wait for Phase 2, because risk profiles do not exist until the risk layer is built. Phase 1 has a pass-through gate so that the event flow is already the final one.
- **The holdout** arrives with the first backtest (PR 15), earlier than the improvement loop that needs it, so that no Phase 1 experiment uses it up.

## Carried into later phases

| Commitment | Phase |
|---|---|
| Risk-profile sweeps and side-by-side profile comparison | 2 (PR 5) |
| ~~Walk-forward, sweep and capital reports say which runs the drawdown kill halted~~ Done in PR 5 (ADR-0036) | 2 (PR 5) |
| Paper and live rebuild the signals windows from the cache at every start and after a split refetch, through `SignalsStage.warm_up` (ADR-0021) | 2 (PRs 7, 14) |
| Revised promotion criteria with a paper-versus-backtest tracking threshold, as an ADR for approval | 2 (PR 19) |
| User guide page on what protects a position within a session ([ADR-0015](docs/adr/0015-daily-loss-limit.md)) | 2 (PR 20) |
| Maintenance runbook: update `exchange_calendars` regularly, because unscheduled market closures only appear after a library update | 2 (PR 20) |
| ~~Simulated broker credits distributions as cash at the ex-date, and documents that rule (ADR-0019)~~ Done in PR 10: [backtesting internals](docs/developer-guide/backtesting-internals.md) | 1 (PR 10) |
| Withholding tax on US dividends paid to a Canadian resident: verify the rate and IBKR's handling, then model it | 4 (moved by the Phase 2 plan) |
| Trial registry, holdout and deflated results inside the automated gate | 3 |
| Paper and live keep the sleeve book across restarts (stored, or rebuilt from fills) and reconcile it with the broker's positions; execution places a stop only after the broker reports the entry's fill (ADR-0023) | 2 (PRs 7, 13, 14) |
| A day order still open at the next decision (possible live, impossible in the simulator) currently halts the run; decide how live execution handles it | 2 (PR 14) |
| Paper and live confirm each stop's cancellation before a flatten's sale goes out; the simulator cancels at once (ADR-0039) | 2 (PRs 11, 14) |
| How to cancel an order in IBKR's own apps, checked on the paper account, written into the `kill-switch` runbook | 2 (PR 10) |
| The paper cycle builds the gate with `FlagFileKillSwitch` and reports an engaged switch or a halt at startup (ADR-0039) | 2 (PR 14) |
| The paper run subscribes `AlertCollector`, sends its alerts after the run and `run_failed_alert` when it fails (ADR-0040) | 2 (PR 14) |
| Alerts for a reconciliation mismatch, a run that did not happen, and a gateway that needs a login (brief §9) | 2 (PRs 13, 15, 17) |
| Log retention: `logs/` is never pruned; decide a rule if it grows | 2 (PR 20) |
| A lock so `tyche kill` and `tyche resume` cannot run during a cycle | 2 (PR 15) |
| Whether reconciliation's halt needs the planned `HaltEvent`, or is carried on the approval like the drawdown halt and the kill switch | 2 (PR 13) |
| Paper and live fetch exactly the candidate list in the market profile (ADR-0024); `tyche data fetch` could fetch the whole list in one command | 2 (PR 12) |
| `starting_cash` is in the profile's first cash currency; `CA+US` needs cash per currency | 4 |
| The Phase 3 promotion check is the one code path allowed to read the holdout, and records that it did (ADR-0024) | 3 |
| Interest on cash in the simulator, and a real risk-free rate (such as T-bills) for Sharpe and Sortino, in one change (ADR-0025) | After Phase 2 |
| ~~A command to measure an existing record from its `equity.csv` and `fills.csv`, if the report needs it~~ Not needed: the report reads `metrics.json` (ADR-0028) | 1 (PR 19) |

## Open decisions

| Decision | Needed by |
|---|---|
| Branch protection for `main`: a PR is required and force-pushes are blocked (done 2026-11-23); still to do: require the CI check to pass. A GitHub setting only you can change | Now, recommended |
| PR 22's proposed defaults for a small account: Tiered for the real account (yours to choose at IBKR); low turnover below USD 10,000 ([ADR-0031](docs/adr/0031-minimum-viable-capital.md)). The positions part is decided: one risk profile per live stage (PR 5, ADR-0036) | Before paper trading (PR 14) |
| Whether the Phase 3 gate deflates a Sharpe ratio against zero (the paper's test, what PR 21 reports) or against the benchmark's Sharpe ratio. Against zero, holding SPY from 2005 to 2023 passes at 99.3% (ADR-0030) | Phase 3 gate; worth a view in PR 21's review |
| Scheduler: APScheduler or cron in the container | Phase 2, PR 15 |

Decisions that belong to a Phase 1 PR are listed in the plan above.

## To verify against current sources (not from memory)

| Fact | Where |
|---|---|
| ~~IBKR Canada commissions, minimums and fractional-share rules~~ Done 2026-11-17: Fixed USD 0.005 a share, min USD 1.00, max 1%; no fractional orders through the API | Phase 1, PR 9 |
| ~~Settlement rules for an IBKR Canada cash account~~ Done 2026-11-17: T+1, settled cash only, free-riding rule | Phase 1, PR 9 |
| Whether an IBKR Canada cash account can spend unsettled proceeds (IBKR's pages disagree), and when on the settlement date proceeds count as settled | Phase 2, PR 10 |
| Whether GST or PST applies to stock commissions for a Canadian resident | Phase 2, first statement |
| FINRA Trading Activity Fee rate after its holiday ends on 2026-12-31 | Phase 2, PR 10 |
| ~~yfinance limits, terms and adjusted-price behaviour~~ Done 2026-11-17: personal use only, no documented rate limit, "unadjusted" prices are split-adjusted (ADR-0019) | Phase 1, PR 6 |
| ~~Licences of the candidate reference backtesters~~ Done 2026-11-19: backtesting.py 0.6.6 AGPL-3.0; vectorbt 1.2.1 Apache-2.0 with the Commons Clause | Phase 1, PR 17 |
| Linux wheels for all dependencies on Python 3.14 (Docker) | Phase 2, PR 18 |
| IB Gateway ports, account-id formats, IBC behaviour, 2FA flow | Phase 2, PRs 10 and 17 |
| `claude -p` flags, output format and plan limits | Phase 3 |

## Known issues and risks

The honest notes, with what was agreed for each, are in the [system overview, section 9](docs/architecture/system-overview.md#9-assumptions-and-honest-notes).

## Next

**PR 9 is in review.** To try it on your own workspace: create a webhook in a private Discord channel, put it in `.env` ([Discord alerts, secrets and logs](docs/user-guide/09-discord-alerts-and-logs.md)), then run `uv run tyche config check` and `uv run tyche notify test`. Please also read [ADR-0040](docs/adr/0040-logs-secrets-and-alerts.md) and accept it or say what to change.

If you have not yet, create the three stage profiles in your own workspace ([profiles for a small account](docs/user-guide/08-risk-profiles.md#profiles-for-a-small-account)) and set its guardrails for stage 1. After PR 9 merges: **Phase 2, PR 10 (IBKR facts, written and dated)**, when you say to start it. It needs no code, but it does need your IBKR paper account for the facts the documents disagree on.

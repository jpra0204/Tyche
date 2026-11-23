# Changelog

All notable changes to Tyche are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/). While the version is below 1.0, each completed roadmap phase raises the minor version.

## [Unreleased]

### Added

- Risk limits in three layers (Phase 2, PR 1, ADR-0032): `config/guardrails.toml` with a ceiling for every profile limit and capital and order caps per cash currency; named risk profiles in `config/risk/`, `default` shipped with the brief's values; an optional `[risk]` table in a strategy file that may only tighten position rules. Every layer is checked against the one above at startup, each breach named with its file, key, value and limit.
- `tyche config check --risk-profile <name>`, which also prints the active profile, the other valid profiles, the guardrails and each strategy's own limits.
- User guide: risk profiles and guardrails. Learning note: layered limits.
- The risk gate's position rules (Phase 2, PR 2, ADR-0033): `RiskGate` replaces `PassThroughGate` and applies risk per trade (entries and additions with a stop, at the decision's close, never trimming a holding), max open positions (per sleeve, then the account; held positions keep their place, new entries fill free places largest first) and max position size (per sleeve, then per instrument across sleeves, every contribution shrunk by the same proportion). It only lowers or removes contributions. Every cut is a `RiskEvent`, and `ApprovedPortfolioEvent` gains `adjustments`. The rules are the pure function `review`, covered by property-based tests.
- `--risk-profile <name>` on `tyche backtest`, `walk-forward`, `sweep` and `capital` (default `default`). The run record gains `risk` (the profile's values and each strategy's own limits) and `outcome.risk_adjustments`; the backtest summary and the report show both.
- `RiskAdjustment`, `RiskRule`, `RiskScope` and `RiskAction` in `tyche.core.domain`; `RiskLimits` in `tyche.core.risk`.
- Learning note: functional core, imperative shell.
- Order-level guardrails (Phase 2, PR 3, ADR-0034). When a run is given the guardrails' money caps (paper and live; research backtests are not), execution sizes weights on the lower of equity and `max_total_capital`, and cuts each purchase to fit `max_order_value` and what is left under `max_total_capital`. A cut is a `RiskEvent` carrying an `OrderAdjustment`, and the plan note is `capped`. Sales are never cut. Long only and no leverage are checked on every decision of every run, and a breach halts it.
- `MoneyLimits` and `OrderAdjustment` in `tyche.core.domain`; `Guardrails.money_limits()`; `BacktestSpec.money_limits`; `ExecutionPlanEvent.sized_on`; `risk.money_caps` in the run record.
- The account rules (Phase 2, PR 4, ADR-0015, ADR-0035). The risk gate measures equity at every close. **Daily loss limit:** a loss of at least the limit since the previous close blocks every entry and addition at that close; exits and reductions go through. **Drawdown kill:** a fall of at least the limit below the highest close halts trading for the rest of the run: the gate approves nothing, execution keeps every holding and sends no order (plan note `halted`), and resting stops stay. A halted backtest runs on to its last day. Each trigger is a `RiskEvent` carrying an `AccountTrigger`; `ApprovedPortfolioEvent` gains `halt`.
- `AccountTrigger`, `ACCOUNT_RULES`, `RiskRule.DAILY_LOSS_LIMIT` and `RiskRule.DRAWDOWN_KILL` in `tyche.core.domain`; `AccountRules` in `tyche.core.risk`; `BacktestResult.triggers` and `.halt`. The run record gains `outcome.account_rules`; the backtest summary gains an `Account rules:` line; the report warns of a halt and marks it on the equity and drawdown charts.
- Learning note: circuit breakers and latches.
- `tyche compare-profiles --from <date> [--risk-profile <name>]...` (Phase 2, PR 5, ADR-0036): the configured strategies once per risk profile (every profile in `config/risk/` by default), over the same days, side by side. Writes `reports/profiles/<id>/` with `profiles.json`, each profile's full backtest record under `runs/<profile>/`, and `report.html`: one table and one equity and drawdown chart for every profile against the benchmark, every halt marked, and what each profile's limits did. It names no best profile and adds no trial; the report warns that choosing on these results is a selection. `tyche report <id>` rebuilds it.
- Sweep trials (`trials.json`) and capital runs (`capital.json`) record `halted_at`; the sweep, walk-forward and capital reports warn of every run the drawdown kill halted.
- User guide: comparing profiles side by side, and one risk profile per live stage for a small account (`stage-1`, `stage-2`, `stage-3`, created in your workspace, not shipped).

### Changed

- **Backtests now trade within a risk profile, `default` unless you choose another.** Results differ from earlier runs: under `default` (20% per position) buy-and-hold SPY from 2005 to 2023 ends at 14,568 USD instead of 52,168, the trend rotation at 23,464 instead of 30,049, the mean reversion at 10,650 instead of 12,735. Under a profile whose limits do not bind, all three reproduce their earlier results to the cent.
- **The daily loss limit and the drawdown kill now apply** (PR 4). Under `default`, from 2005 to 2023, the trend rotation halts on 2020-03-18 (15.11% below its peak) and, holding its three funds untouched from then on, ends at 25,915 USD instead of 23,464, with a worst fall of 20% instead of 15%. Buy-and-hold and the mean reversion never trigger either rule and are unchanged.
- A workspace now needs `config/guardrails.toml` and `config/risk/default.toml`; Tyche refuses to start without them. Copy them from a new workspace ([troubleshooting](docs/user-guide/07-troubleshooting.md#upgrading-a-workspace-created-by-an-older-tyche)).
- The config hash now covers the guardrails and the active risk profile, so every workspace's hash changes once. Trial counts are unaffected.

## [0.1.0] - 2026-11-23

Phase 1: core and backtesting, for the `US` profile at end of day. Tyche fetches daily data from Yahoo Finance into a private workspace, and backtests strategies on it through the whole trading path (universe, screening, signals, portfolio, a pass-through risk gate, execution, a simulated broker with IBKR's costs and T+1 settlement), against SPY's total return. It reserves a holdout, records every run, checks its own engine against backtesting.py, reports in HTML, tests out of sample with walk-forward, counts every trial behind a parameter sweep and deflates its Sharpe ratio, and measures the account size each strategy needs. No paper or live trading yet.

### Added

- Domain types in `tyche.core.domain`: `Currency`, `Money`, `Timeframe`, `Instrument`, `AssetClass` and `Bar` (Phase 1, PR 1).
- Learning note on value objects.
- Event bus in `tyche.core.events`: the `Event` base class, the `Envelope` with automatic causation, and the synchronous `EventBus` with run-to-completion dispatch and fail-closed error handling (Phase 1, PR 2).
- `Clock` and `Calendar` ports, the `Session` value object, `SimClock`, and a calendar adapter backed by `exchange_calendars` (Phase 1, PR 3).
- Learning note on time as a port.
- First runtime dependency: `exchange_calendars` (Apache-2.0).
- `tyche init`: creates a private workspace from packaged templates, refusing unsafe locations and never overwriting (Phase 1, PR 4).
- `tyche config check`: validates the workspace configuration and prints its fingerprint.
- Workspace configuration: `config/tyche.toml` and the `US` market profile, validated by pydantic file schemas and the new `MarketProfile` domain object, with a config hash.
- ADR-0016 (Typer) and ADR-0017 (config schemas at the boundary).
- User guide: installation and your workspace. Learning note: config at the boundary.
- Runtime dependencies: `pydantic` (MIT) and `typer` (MIT).

- Market data layer (Phase 1, PR 5): the `DataProvider` port; `BarHistory` and the calendar-based data-quality audit; a Parquet bar cache that records fetch times and coverage; a read-through `CachedDataProvider` over any `BarSource`.
- ADR-0018 (audit market data). Learning note: working with unreliable data.
- Runtime dependency: `pyarrow` (Apache-2.0). Development dependency: `pyarrow-stubs` (BSD-2-Clause).

- Corporate actions (Phase 1, PR 6a): `PriceAdjustment`, `CashDistribution` and `Split` in the domain; `BarHistory` returns the distributions and splits in its window; the cache stores them exactly; a new split triggers a full refetch of the instrument's history (ADR-0019).

- `tyche data fetch` (Phase 1, PR 6b): downloads daily bars, dividends and splits from Yahoo Finance into the workspace cache, audited against the calendar.
- `YFinanceSource`: stamps bars at session closes, retries rate limits and network failures with exponential backoff, fails at once on unknown symbols.
- `SystemClock`, the real-time `Clock`, and a table of known US exchanges.

- User guide: fetching market data. Developer guide: how to add a data source.
- `network` test marker for opt-in tests against real services.
- Runtime dependency: `yfinance` (Apache-2.0). Development dependency: `pandas-stubs` (BSD-3-Clause).

- Engine and replay (Phase 1, PR 7): `Engine` (one run loop for every mode), `HistoricalReplay` (a `Feed` that plays cached history session by session), `InMemoryJournal`, the `Feed` and `PacedClock` ports, and the events `SessionEvent`, `BarEvent`, `DataReadyEvent`, `DataQualityEvent` and `RunEvent`.
- Learning note: lookahead bias.

- Account ledger (Phase 1, PR 8): `Order` and its `OrderState` lifecycle, `Fill`, `Position`, and an immutable `Account` with cash per currency (settled and unsettled), positions at average cost, marks and realised profit. Refuses short sales, buying beyond the cash and applying a fill twice.
- `Money.round_to`, banker's rounding at an explicit number of places.
- Property-based tests for the ledger. Learning note: property-based testing.
- Development dependency: `hypothesis` (MPL-2.0).

- IBKR Canada costs and settlement, checked 2026-11-17 and written up with sources; ADR-0020 (cost and settlement model) accepted (Phase 1, PR 9).
- `TradingCosts` in the domain: IBKR Pro Fixed commissions (`CommissionSchedule`), regulatory fees rounded up to the cent (`RegulatoryFees`), adverse slippage, and `TradeCost`. Whole-share sizing with `whole_shares` and `affordable_shares`.
- `settlement_date` in `tyche.core.sim`: T+n sessions on the trading calendar.
- Workspace file `config/costs/US.toml` with the rates and the date they were checked; decimals must be quoted strings. `tyche config check` prints that date. Learning note: costs as data.

- `SimBroker` (Phase 1, PR 10): the `Broker` port for backtests. Market orders fill at the next open; sell stops fill at the open on a gap or at the stop when the low reaches it; slippage and costs per fill; at most a set share of each bar's volume, so day orders can fill partly and expire; purchases from settled cash only; T+1 settlement; free-riding violations recorded; repeated order ids ignored; cash distributions credited to holders at the ex-date.
- The `Broker` port, and the events `OrderEvent`, `FillEvent` and `DistributionEvent`. `HistoricalReplay` publishes distributions at the open of their ex-date.
- `Account.receive_distribution` and `Account.distributions_received`: dividends are income, kept apart from deposits.
- Developer guide: backtesting internals.

- Universe and screening (Phase 1, PR 11): `UniverseStage` publishes a `UniverseEvent` at every decision cycle, listing each expected instrument as eligible (with its last close and average dollar volume) or excluded with an `ExclusionReason`: outside the profile, no bar, a recent data problem, too little history, price below the minimum, or too little dollar volume. `ScreeningStage` ranks the eligible instruments with a `Screen` and publishes a `ScreeningEvent`; `DollarVolumeScreen` ranks by liquidity.
- `UniverseRules`, `UniverseMember`, `Exclusion`, `ScoredInstrument` and `DISQUALIFYING_ISSUES` in the domain.
- Backtesting internals: which instruments are considered. Learning note: state built from events.

- Strategy interface and signals (Phase 1, PR 12): the `Strategy` protocol and the read-only `StrategyContext` it is handed at every cycle (ranking, exactly `lookback` bars per offered instrument, instruments still warming up, the strategy's own positions); `BarWindows` keyed by instrument and timeframe, with one warm-up path; `SignalsStage`, which checks every strategy's targets and records a failing strategy without halting the run; `SignalEvent` and `SignalsReadyEvent`; `Target`, `StrategyPosition`, `WarmingUp` and `StrategyFailure` in the domain.
- `BuyAndHold`, the benchmark strategy, in `tyche.strategies`.
- ADR-0021 (strategies see a window handed in). Developer guide: how to add a strategy. Learning note: plugins.

- Portfolio construction (Phase 1, PR 13): `PortfolioStage` publishes a `TargetPortfolioEvent` per cycle, in weights of account equity: one `Sleeve` per strategy and one `InstrumentTarget` per instrument, made of `Contribution`s that each keep their strategy's stop (ADR-0022).
- Strategy config: a `[strategies]` table of budgets in `config/tyche.toml` and one `config/strategies/<id>.toml` per instance; the `PLUGINS` registry in `tyche.strategies`, each plugin with a strict parameter model; `tyche.runtime.strategies.build_strategies`. `tyche config check` builds every strategy and prints the budgets and the cash left.
- ADR-0022. User guide: choose your strategies. Backtesting internals: how strategies share the account.

- Risk gate and execution (Phase 1, PR 14): `PassThroughGate`, the only publisher of `ApprovedPortfolioEvent`, approves every proposed portfolio unchanged until Phase 2. `ExecutionStage` sizes approved weights into whole shares of equity at the last close, keeps holdings inside a rebalance band, crosses shares between sleeves before netting the rest into one market order per instrument, fits purchases to the buying power at the next open with a price buffer, splits fills between sleeves pro rata, and places each protective stop when its entry fills (ADR-0023).
- `SleeveBook`: each strategy's own share of every position, with its resting stop. The signals stage now shows each strategy its positions.
- `AccountState`: Tyche's own view of the account, kept from the same fills, settlements and distributions as the broker's, published as an `AccountEvent` at every session close.
- Events `ApprovedPortfolioEvent`, `ExecutionPlanEvent`, `CancelRequestEvent` and `AccountEvent`. `SimBroker` cancels an open order on request.
- `ExecutionRules`, `PlanLine` and `PlanNote` in the domain; `CashBalance.buying_power` and `Account.credit`.
- `tyche config check` prints the rebalance band and the price buffer.
- ADR-0023. Backtesting internals: from approved weights to orders. Learning note: sub-ledgers that add up.

- `tyche backtest` (Phase 1, PR 15): runs the configured strategies on cached history through the whole trading path and writes a run record to `reports/backtests/<run id>/` in the workspace: `run.json` (code version, config hash and every setting, range, warm-up, holdout, data used, outcome), `equity.csv` and `fills.csv`. The first end-to-end backtest.
- The holdout: history from `holdout_starts` (2024-01-01 in the template) is refused to every backtest (ADR-0024).
- `run_backtest`, `BacktestSpec`, `BacktestResult`, `BacktestSettings`, `HoldoutError` and `BacktestError` in `tyche.core.backtest`. `UniverseStage.warm_up` and `history_needed`, so the first decision is judged on the sessions before it.
- `CacheOnlySource` and `NotCachedError`: a backtest reads only the cache and names the `tyche data fetch` command for anything missing.
- `TycheConfig.backtest` and `TycheConfig.snapshot`; `Workspace.reports_dir`.
- ADR-0024. User guide: running a backtest. Backtesting internals: the backtest runner. Learning note: the holdout and the run record.

- Metrics (Phase 1, PR 16): `tyche.core.backtest.metrics` measures a run and its benchmark the same way: CAGR, volatility, Sharpe and Sortino (risk-free rate zero), maximum drawdown with its dates, exposure, turnover, costs, closed trades and win rate, and each figure's difference from the benchmark. `measure`, `measure_backtest`, `series_metrics`, `benchmark_points`, `closed_trades` and their result types; `MetricsError`.
- The benchmark is the total return of the market profile's index ETF, distributions reinvested at the ex-date close, no costs, no cash (ADR-0025). `BacktestResult.benchmark` holds its history.
- `tyche backtest` prints the metrics beside the benchmark's, and the record gains `metrics.json`, a `benchmark_equity` column in `equity.csv`, and the benchmark and its data in `run.json`.
- A golden-file regression test pins every metric of a fixed backtest.
- ADR-0025. Backtesting internals: metrics. Learning notes: measuring against a benchmark, golden-file tests.

- Reference validation (Phase 1, PR 17): `tests/reference/` runs one strategy through Tyche and through backtesting.py on the same bars and compares every fill, the equity at every close, every closed trade and the metrics. In CI on a seeded random walk at USD 10,000 and USD 1,000,000; on demand (`-m network`) on real SPY bars from 2005 to 2023. They agree to within 10⁻⁹ USD.
- An import-linter contract: Tyche never imports the reference backtester.
- ADR-0026. Backtesting internals: checked against an independent engine. Learning note: reference validation.
- Development dependency: `backtesting` (AGPL-3.0), test-only and never imported by Tyche.

- Example strategies (Phase 1, PR 18), with their rules fixed before any backtest (ADR-0027): `TrendRotation` (`trend_rotation`) holds, from the first session of each month, the three of its ETFs with the highest 126-session return that are above their 200-session average; `MeanReversion` (`mean_reversion`) buys an RSI(2) dip below 10 above the 200-session average, with a stop 2.5 ATR(14) below the close kept for the life of the trade, and sells above the 5-session average.
- `tyche.strategies.indicators`: `simple_average`, `price_return`, `rsi` (Wilder's) and `average_true_range`.
- Strategy parameters: `InstrumentParameters` for lists of instruments and `ExactDecimal` for decimals written as strings.
- New workspaces get `config/strategies/trend_rotation.toml` and `mean_reversion.toml`, without a budget, so they do not run until given one.
- ADR-0027. User guide: trying the example strategies. Developer guide: indicators, list and decimal parameters. Learning note: strategies without memory.

- Backtest report (Phase 1, PR 19): `tyche backtest` writes `report.html` into each measured run's record folder, and `tyche report <run id>` rebuilds it from the record alone. One self-contained HTML file with charts drawn by matplotlib as inline SVG, deterministic, about 300 to 400 KB. Sections: summary against the benchmark (equity and drawdown charts), year by year, trading and exposure, cost drag, what ran, data and its limits (ADR-0028).
- `cost_drag` and `fill_cost` in `tyche.core.backtest`: the run measured before and after its costs, slippage worked back from fill prices. `yearly_returns`: the return of each calendar year.
- `tyche.adapters.reports`: a small `Document` model and `render_html`.
- ADR-0028. User guide: the report. Learning note: reports built from the record.
- Runtime dependency: `matplotlib` (PSF-based licence), with numpy. The core's import contract now forbids `matplotlib`.

- Walk-forward (Phase 1, PR 20): `tyche walk-forward --from <date>` cuts history into folds of calendar years (by default anchored, a five-year first training window and one-year test windows; `--train-years`, `--test-years`, `--rolling`), runs every training and test window as a backtest of its own from the starting cash, and reports in-sample and out-of-sample results side by side. The test windows are joined into one out-of-sample result against the benchmark joined the same way. A train step between each fold's runs keeps the configured parameters until parameter sweeps (PR 21) (ADR-0029).
- `plan_folds`, `FoldScheme`, `Fold`, `Window`, `chain`, `measure_walk_forward`, `FoldResult` and `WalkForwardMetrics` in `tyche.core.backtest`.
- Each walk-forward writes `reports/walk_forward/<id>/`: `walk_forward.json`, `metrics.json`, `equity.csv`, `report.html`, and each window's full backtest record under `folds/`.
- ADR-0029. User guide: walk-forward. Learning note: walk-forward testing and overfitting. Developer guide: backtesting internals, section 9.

- Parameter sweeps (Phase 1, PR 21): `tyche sweep <name> --from <date>` runs every combination of the values in `config/sweeps/<name>.toml` as a backtest over the same days, picks the highest Sharpe ratio, and reports the pick with a deflated Sharpe ratio (Bailey and López de Prado, 2014) and overfitting warnings: not significant at 95%, a pick at the edge of the grid, an isolated peak, trials that failed (ADR-0030).
- Trials are counted for good: every distinct trial of a plugin (its version and full parameters) recorded anywhere under `reports/`, plus the sweep's own, is the `N` the pick is deflated for.
- `tyche walk-forward --sweep <name>`: each training window runs every combination, and its test window runs the pick. Each combination counts as one trial, however many folds run it.
- Each sweep writes `reports/sweeps/<id>/`: `sweep.json`, `trials.json` (every trial's parameters, key and metrics), the pick's full backtest record in `pick/`, and `report.html`. Other trials keep no equity or fills.
- `Grid`, `combinations`, `pick`, `trial_key`, `expected_max_sharpe`, `probabilistic_sharpe`, `deflated_sharpe`, `return_moments`, `session_sharpe` and `overfitting_warnings` in `tyche.core.backtest`; `load_sweep` and `SweepSpec` in `tyche.config`; `recorded_trial_keys` in `tyche.runtime.trials`.
- New workspaces ship an example sweep, `config/sweeps/trend_rotation.toml` (27 combinations).
- ADR-0030. User guide: parameter sweeps. Learning note: multiple testing and the deflated Sharpe ratio. Developer guide: backtesting internals, section 10.

- Minimum viable capital (Phase 1, PR 22): `tyche capital --from <date>` runs each configured strategy alone, with the whole account and its configured parameters, at several starting amounts (`--amounts`, default USD 500 to 25,000) and on a reference account (`--reference`, default USD 100,000; a reference whose orders the volume cap cut short is flagged as too large), under IBKR Pro Fixed and Tiered. An amount is viable when its CAGR after costs is within the tolerance of the reference account's, either way (`--tolerance`, default half a point a year); the minimum viable capital is the smallest amount from which every larger amount tested is viable. Each is reported beside the benchmark, which says whether there is an edge to keep (ADR-0031).
- IBKR Pro Tiered as a pricing plan: `TieredSchedule` in `tyche.core.domain` (first volume tier, pass-through and clearing fees, and an assumed exchange fee per share), and an optional `[tiered]` table in `config/costs/<PROFILE>.toml`. Backtests still use `[commission]`; `tyche capital` compares the two.
- Beside the backtests, two pieces of arithmetic: what one round trip costs per position, for 1 to `--positions` positions (default 5) at USD 100 a share; and how many whole shares of each candidate one position buys at its latest cached close. That close may lie inside the holdout: only its price is read.
- Each analysis writes `reports/capital/<id>/`: `capital.json` and `report.html`. Each strategy in it counts as one trial.
- `size_penalty`, `is_viable`, `minimum_viable` and `round_trip_cost` in `tyche.core.backtest`.
- ADR-0031. User guide: minimum viable capital. Learning note: what account size costs. Developer guide: backtesting internals, section 11; IBKR facts re-checked on 2026-11-22, with exchange fees and the CAD/USD rate used.

- Phase 1 wrap-up (PR 23): version 0.1.0. Developer guide: pipeline contracts, what each stage takes in, promises, keeps and does on failure. User guide: troubleshooting, with one table for upgrading a workspace created by an older Tyche. Every user-guide command re-run in a fresh workspace, and stale notes removed.

### Changed

- ADR-0031 accepted (2026-11-23). Its proposed small-account defaults are not adopted; they stay open for Phase 2.
- `TradingCosts.commission` is a `Commission`: the Fixed `CommissionSchedule` or the new `TieredSchedule`. `TycheConfig` gains `tiered_costs`.
- The config snapshot, and so the config hash, leaves out an optional table that is absent. No existing file has one, so no existing hash changes; a new workspace's hash differs from an older one's because its costs file has `[tiered]`.
- `tyche report` also finds capital analyses; its error for an unknown id now reads `no backtest, walk-forward, sweep or capital record named …`.

- A backtest's `run.json` states each strategy's parameters (`strategies[].parameters`), so a trial can be counted. The record format stays 1: the field is added.
- `build_strategies` takes overrides of a strategy's parameters, and `ConfiguredStrategies` carries the parameters each strategy was built from. `tyche.runtime.backtest.run_and_record` is split into `run_and_measure` and `record_run`.
- A walk-forward's progress callback is also told the parameters a sweep picked (`None` without a sweep). `tyche report` also finds sweeps; its error for an unknown id now reads `no backtest, walk-forward or sweep record named …`.

- `tyche report <id>` also rebuilds a walk-forward's report, and its error for an unknown id now reads `no backtest or walk-forward record named …`.
- A backtest's `run.json` gains `part_of` when the run is one window of a walk-forward. The record format stays 1: no field changed meaning.
- `tyche.runtime.backtest` is split into `checked_range`, `cached_market` and `run_and_record`, so a walk-forward runs each window exactly as `tyche backtest` does. `tyche.runtime.report` exposes its formatting helpers and `data_limits` for the walk-forward report.

- The `US` market profile template lists nine candidate ETFs instead of two: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD and VNQ. A backtest replays every candidate, so a new workspace must fetch all nine (two `tyche data fetch` commands, one per exchange). Existing workspaces keep their own list.

- `config/markets/<PROFILE>.toml` requires a `[benchmark]` table (`symbol`, `exchange`, `asset_class`), and `MarketProfile` gains a required `benchmark`, which must follow one of the profile's calendars and trade in one of its cash currencies. A workspace created before PR 16 must copy the table from a new one (user guide, running a backtest, troubleshooting).

- `config/tyche.toml` requires a `[backtest]` table (`holdout_starts`, a TOML date, and `starting_cash`), and `config/markets/<PROFILE>.toml` requires an `instruments` list under `[universe]`: the candidates a backtest replays. `UniverseRules` gains `instruments`, checked against the thresholds' currency, the allowed asset classes and the profile's calendars. A workspace created before PR 15 must copy both from a new one (user guide, running a backtest, troubleshooting).

- `MarketProfile` has a required `execution` (`ExecutionRules`: `rebalance_band` and `price_buffer`), read from a new `[execution]` table in `config/markets/<PROFILE>.toml`. A workspace created before PR 14 must copy the table from a new one (user guide, installation, troubleshooting).

- `config/tyche.toml` requires a `[strategies]` table, and each strategy named there needs its file in `config/strategies/`. A workspace created before PR 13 must add both (user guide, installation, section 5).
- `SignalEvent` gains `offered`, the instruments the strategy decided on.
- `MarketProfile` has a required `universe` (`UniverseRules`), read from a new `[universe]` table in `config/markets/<PROFILE>.toml`, and the config hash covers it. A workspace created before PR 11 must copy the table from a new one.

- `load_config` now also requires `config/costs/<PROFILE>.toml`, and the config hash covers it. A workspace created before PR 9 must copy the file from a new one.
- `Bar.is_adjusted` (a yes/no flag) is replaced by `Bar.adjustment`, a `PriceAdjustment`. Cache files move to format 2.
- `BarSource.fetch_daily` returns `SourceData` (bars, distributions, splits and the source's own issues) instead of a list of bars.

- ADR-0017 and ADR-0018 accepted.

- The CLI is built with Typer instead of `argparse`. Running `tyche` with no arguments now prints help and exits with code 2.
- pytest now treats every warning as an error. One known warning raised inside `exchange_calendars` is ignored, with the reason and the condition for removing it in `pyproject.toml`.

### Fixed

- The data cache could not record sessions before an instrument's first bar when a fetch for them returned nothing, so a backtest or sweep whose warm-up reached back before GLD (November 2004) or VNQ (September 2004) existed kept printing the same `tyche data fetch` hint. An empty answer for sessions that all fall before the earliest cached bar now marks them as covered; the audit still reports them as missing sessions. Empty answers for sessions after the last cached bar are asked for again, as before.
- `SimBroker` paid each purchase from settled cash without subtracting purchases made earlier at the same open, so two purchases could each pass the check and then fail in the ledger, halting the run. It now uses the account's buying power: settled cash minus purchases not settled yet (PR 14).

## [0.0.1] - 2026-11-16

Phase 0: plan and scaffolding. No trading functionality.

### Added

- Architecture documentation: system overview, event catalog and agent architecture.
- ADRs 0001 to 0015.
- `CLAUDE.md`, `STATUS.md`, `README.md` and this changelog.
- Developer guide (repo map, conventions), learning notes (event-driven design, hexagonal architecture, backtest/paper/live parity, the gated agent loop) and index pages for the user guide and runbooks.
- Python 3.14 project managed by `uv`, with a locked development toolchain: ruff, mypy (strict), pytest, import-linter.
- Package skeleton under `src/tyche/` with one documented package per architectural area.
- Five import-linter contracts that enforce the architecture in CI.
- `tyche --version` command.
- GitHub Actions workflow running lint, format check, type check, import contracts and tests.
- `.env.example` and `.gitignore`.

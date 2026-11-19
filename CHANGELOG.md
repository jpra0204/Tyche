# Changelog

All notable changes to Tyche are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/). While the version is below 1.0, each completed roadmap phase raises the minor version.

## [Unreleased]

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

### Changed

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

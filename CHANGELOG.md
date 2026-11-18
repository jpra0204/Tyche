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

### Changed

- `load_config` now also requires `config/costs/<PROFILE>.toml`, and the config hash covers it. A workspace created before PR 9 must copy the file from a new one.
- `Bar.is_adjusted` (a yes/no flag) is replaced by `Bar.adjustment`, a `PriceAdjustment`. Cache files move to format 2.
- `BarSource.fetch_daily` returns `SourceData` (bars, distributions, splits and the source's own issues) instead of a list of bars.

- ADR-0017 and ADR-0018 accepted.

- The CLI is built with Typer instead of `argparse`. Running `tyche` with no arguments now prints help and exits with code 2.
- pytest now treats every warning as an error. One known warning raised inside `exchange_calendars` is ignored, with the reason and the condition for removing it in `pyproject.toml`.

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

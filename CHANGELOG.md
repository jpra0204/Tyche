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

### Changed

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

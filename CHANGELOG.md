# Changelog

All notable changes to Tyche are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/). While the version is below 1.0, each completed roadmap phase raises the minor version.

## [Unreleased]

### Added

- Domain types in `tyche.core.domain`: `Currency`, `Money`, `Timeframe`, `Instrument`, `AssetClass` and `Bar` (Phase 1, PR 1).
- Learning note on value objects.
- Event bus in `tyche.core.events`: the `Event` base class, the `Envelope` with automatic causation, and the synchronous `EventBus` with run-to-completion dispatch and fail-closed error handling (Phase 1, PR 2).

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

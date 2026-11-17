# Status

*Last updated: 2026-11-16*

## Current phase

**Phase 0: Plan. Complete, awaiting Pablo's review.** Phase 1 does not start until the Phase 0 pull request is approved and merged.

## What works today

- `uv sync` installs a pinned Python 3.14 environment.
- `make check` passes: ruff lint and format, mypy strict, five import-linter architecture contracts, pytest.
- `tyche --version` runs.
- CI runs the same checks on every pull request and on `main`.

There is no trading, data or backtesting code yet. Every package under `src/tyche/` except `cli` contains only a docstring saying what will live there.

## What Phase 0 delivered

- Architecture: [system overview](docs/architecture/system-overview.md), [event catalog](docs/architecture/event-catalog.md), [agent architecture](docs/architecture/agent-architecture.md).
- [14 ADRs](docs/adr/README.md).
- `CLAUDE.md`, this file, `CHANGELOG.md`, `README.md`.
- Developer guide ([repo map](docs/developer-guide/repo-map.md), [conventions](docs/developer-guide/conventions.md)) and four [learning notes](docs/learning/README.md).
- Index pages for the user guide and runbooks, listing each planned page and the phase that writes it.
- Repo scaffolding: `pyproject.toml`, lockfile, package skeleton, `Makefile`, CI workflow, `.gitignore`, `.env.example`.

## Needs Pablo's decision in the Phase 0 review

Five ADRs are my proposals, not yet agreed:

| ADR | Proposal |
|---|---|
| [0003](docs/adr/0003-synchronous-event-bus.md) | Synchronous, single-threaded, deterministic event bus; no asyncio in the core |
| [0010](docs/adr/0010-config-toml-pydantic.md) | TOML config, pydantic validation, three layers of risk limits |
| [0011](docs/adr/0011-pandas-at-the-edges.md) | pandas only, and never inside events or ports |
| [0012](docs/adr/0012-money-and-time-types.md) | Decimal for money, UTC timestamps, bars stamped at their close |
| [0013](docs/adr/0013-live-trading-gate.md) | The live-trading gate: manual, interactive arming record |

Also proposed: the package layout and import contracts in [ADR-0004](docs/adr/0004-hexagonal-architecture.md).

One assumption to confirm: the meaning of the daily loss limit in an end-of-day system ([system overview, section 9, note 6](docs/architecture/system-overview.md#9-assumptions-and-honest-notes)).

## Open decisions (not blocking Phase 1)

| Decision | Needed by |
|---|---|
| Licence for the public repository (none today, so all rights reserved) | Whenever you want others to use it |
| Turn on branch protection for `main` (require a PR and the CI check); a GitHub setting only you can change | Now, recommended |
| Where to create the private workspace (not under `~/Public`) | Phase 1 |
| CLI framework: stay with `argparse` or adopt Typer | Phase 1 |
| Reference backtester: `backtesting.py` or `vectorbt` (both install on 3.14; licences to check) | Phase 1 |
| How strategies see price history (ADR-0011, point 4) | Phase 1 |
| Scheduler: APScheduler or cron in the container | Phase 2 |
| SQLite migration approach | Phase 2 |
| Opening an IBKR account and its paper account, if not done yet; approval can take days | Before Phase 2 |

## To verify against current sources (not from memory)

| Fact | Phase |
|---|---|
| IBKR Canada commissions, minimums and fractional-share rules | 1 |
| Settlement rules for an IBKR Canada cash account (use of unsettled proceeds) | 1 |
| yfinance limits, terms and adjusted-price behaviour | 1 |
| Linux wheels for all dependencies on Python 3.14 (Docker) | 2 |
| IB Gateway ports, account-id formats, IBC behaviour, 2FA flow | 2 |
| `claude -p` flags, output format and plan limits | 3 |

## Known issues and risks

The honest notes are in the [system overview, section 9](docs/architecture/system-overview.md#9-assumptions-and-honest-notes). The two that matter most:

1. Under $1,000 CAD across up to five positions, per-order minimum commissions may make most simple strategies unprofitable. Phase 1 will measure this.
2. A weekly proposal loop will overfit unless every trial is counted and a holdout is reserved. Designed for in Phase 3.

## Next

After the Phase 0 review: **Phase 1, core and backtesting (`US`, end of day)**. Planned as a sequence of small PRs, starting with the domain types and the event bus.

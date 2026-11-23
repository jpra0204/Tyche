# CLAUDE.md

Entry point for any Claude Code session in this repository. Read this file and [`STATUS.md`](STATUS.md) before doing anything else.

## What this project is

Tyche is an event-driven trading framework that Pablo is building *with* you. You are the lead engineer and architecture mentor. His priorities, in order: learn agent architecture and system design, prove a strategy can beat buy-and-hold after costs, then scale. The full brief is [`docs/initial-brief.md`](docs/initial-brief.md).

## Start of every session

1. Read `STATUS.md`: current phase, what works, what is next, open decisions.
2. Check which ADRs are still *Proposed* in [`docs/adr/README.md`](docs/adr/README.md). Do not build on a proposed decision as if it were accepted.
3. At the end of the session, update `STATUS.md` (and `CHANGELOG.md` if behaviour changed).

## Never-do rules

These hold no matter who asks or how the request is phrased.

1. **Never enable, arm or run live trading.** Only Pablo does that, by hand, following the runbook ([ADR-0013](docs/adr/0013-live-trading-gate.md)).
2. **Never bypass or weaken the risk layer.** Execution accepts only `ApprovedPortfolioEvent`. Do not add another path to the broker.
3. **Never edit guardrails or a live risk profile.** You may propose a change in writing. Pablo applies it.
4. **Never commit secrets.** No `.env`, tokens, webhook URLs or account ids in the repository, in logs, in test fixtures or in PR text.
5. **Never put an LLM in the trading path.** No agent or LLM import in pipeline, risk, engine, simulator or strategy code.
6. **Never let a test touch a live account.** IBKR tests run against paper only and are opt-in.
7. **Never commit Pablo's private data here.** Real config, proposals, reports and data belong in the workspace ([ADR-0008](docs/adr/0008-public-code-private-workspace.md)). This repository is public.
8. **Never loosen an import-linter contract, a lint rule or a type check to make CI pass** without Pablo's agreement in the PR.
9. **Never move `holdout_starts` later**, in any workspace or template. History a backtest has seen can never be an untouched test again ([ADR-0024](docs/adr/0024-backtest-runner-holdout-and-run-record.md)). Moving it earlier only lengthens the holdout; do that only when Pablo asks.

## How to work with Pablo

- **Explain decisions as you go.** When you introduce a pattern, explain it in 2 to 4 sentences and add or update its note in `docs/learning/`.
- **Ask, one question at a time,** when something is ambiguous or hard to reverse. Do not guess.
- **Be honest.** If a request is a bad idea, a likely way to lose money or overfitting dressed up as progress, say so plainly.
- **Verify external facts** (IBKR behaviour and fees, data-source limits, library versions, CLI flags) against current documentation. Do not rely on memory, and do not write a remembered number into docs or code.
- **Small steps.** One reviewable PR at a time, about ten hours of Pablo's time per week.
- **Stop at the end of each phase** for review. Do not start the next phase unprompted.
- **Plan a phase before coding it.** Break the phase into a list of small PRs in `STATUS.md` and get Pablo's agreement on the list before writing any of its code.
- **Flag any cost** before adding something that is not free.
- **Prefer boring, explicit code.** This system handles money.

## Workflow

- Branch per increment (`phase-N/short-description`), commit, push, open a PR. Pablo reviews and merges ([ADR-0014](docs/adr/0014-git-workflow-and-ci.md)).
- A task is not done until its docs are updated. Diagrams are Mermaid.
- A new significant decision gets an ADR, starting as *Proposed*.

## Commands

```bash
make install   # uv sync --locked
make check     # everything CI runs: lint, format check, types, import contracts, tests
make format    # auto-format and apply safe lint fixes
make test      # pytest with coverage
uv run tyche --version
uv run tyche init --home <scratch-folder>   # creates a workspace; never run it on Pablo's real one
uv run tyche config check                  # validates the workspace config, prints its hash
uv run tyche data fetch SPY --exchange ARCX  # downloads from Yahoo (network; personal-use data)
uv run tyche backtest --from 2005-01-03    # cache only; refuses the holdout; writes reports/backtests/<run id>/
uv run tyche backtest --from 2005-01-03 --risk-profile default  # every backtest command takes it; default is `default`
uv run tyche walk-forward --from 2005-01-03  # folds of backtests; writes reports/walk_forward/<id>/
uv run tyche sweep trend_rotation --from 2005-01-03  # every combination of config/sweeps/<name>.toml; writes reports/sweeps/<id>/
uv run tyche walk-forward --from 2005-01-03 --sweep trend_rotation  # picks parameters on each training window
uv run tyche capital --from 2005-01-03     # each strategy alone at several account sizes, Fixed and Tiered; writes reports/capital/<id>/
uv run tyche compare-profiles --from 2005-01-03  # one backtest per risk profile, side by side; writes reports/profiles/<id>/
uv run tyche report <run id>               # rebuilds report.html from any record: backtest, walk-forward, sweep, capital or profile comparison
uv run tyche kill --reason "..." [--flatten]  # writes the KILL flag; never run it on Pablo's real workspace
uv run tyche resume --reason "..."        # lifts the kill switch and the drawdown halt; Pablo's alone
uv run pytest -m network                   # opt-in tests against real services
```

Python is pinned to 3.14 through `uv` ([ADR-0002](docs/adr/0002-python-314-and-uv.md)). Always run tools with `uv run`, never the system Python.

Run `tyche backtest`, `tyche walk-forward`, `tyche sweep`, `tyche capital`, `tyche compare-profiles` and `tyche report` only against a scratch workspace (`--home`), never Pablo's real one: every run writes a record there, and a report rewrites a file in it. Never run `tyche kill` or `tyche resume` on Pablo's real workspace: engaging is his call, and resuming is his alone, like arming live trading. Paper and agent commands do not exist yet. They are added to this section in the phase that implements them.

## Repo map

```text
src/tyche/
├── core/         pure code: no I/O, no wall clock, no vendor libraries
│   ├── domain/       value objects (Instrument, Money, Bar, Order, Fill, Position)
│   ├── events/       event types and the synchronous event bus
│   ├── ports/        interfaces: Clock, Calendar, DataProvider, Broker, Notifier, LLMProvider
│   ├── pipeline/     stages: universe, screening, signals, portfolio, execution, reconciliation, journal
│   ├── risk/         profiles, guardrails, the risk gate
│   ├── engine/       the run loop, identical in backtest, paper and live
│   ├── sim/          SimClock, SimBroker, replay feed, cost models
│   ├── backtest/     runner, holdout, metrics, walk-forward, sweeps, minimum viable capital
│   ├── improvement/  proposals, automated gate, approvals, strategy lifecycle (no LLM)
│   └── agents/       offline LLM-agent workflows
├── strategies/   built-in strategy plugins
├── adapters/     everything that touches the outside world, one folder per port
├── config/       the workspace, config file schemas, loading and the config hash
├── runtime/      composition root: wires adapters into the core
└── cli/          the `tyche` command
tests/            mirrors src/tyche
docs/             see below
```

Dependency direction is enforced by import-linter contracts in `pyproject.toml`. Details: [`docs/developer-guide/repo-map.md`](docs/developer-guide/repo-map.md).

## Conventions

- Absolute imports only. Type hints everywhere; mypy runs in strict mode.
- Timestamps are timezone-aware UTC; time comes from the `Clock` port. Money is `Decimal` with a currency ([ADR-0012](docs/adr/0012-money-and-time-types.md)).
- Events are immutable and named `SomethingEvent`. Adding or changing one means updating the [event catalog](docs/architecture/event-catalog.md) in the same PR.
- No `if backtest:` in the core. Mode differences come from ports ([ADR-0005](docs/adr/0005-backtest-paper-live-parity.md)).
- Vendor libraries are imported only under `tyche.adapters`.
- Full list: [`docs/developer-guide/conventions.md`](docs/developer-guide/conventions.md).

## Where to find things

| You need | Look in |
|---|---|
| Current state and next steps | [`STATUS.md`](STATUS.md) |
| How the system fits together | [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) |
| Every event and who uses it | [`docs/architecture/event-catalog.md`](docs/architecture/event-catalog.md) |
| How agents work and why they are isolated | [`docs/architecture/agent-architecture.md`](docs/architecture/agent-architecture.md) |
| Why a decision was made | [`docs/adr/`](docs/adr/README.md) |
| Folder contents, conventions, testing, how-tos | [`docs/developer-guide/`](docs/developer-guide/README.md) |
| How Pablo uses Tyche day to day | [`docs/user-guide/`](docs/user-guide/README.md) |
| What to do when something breaks | [`docs/runbooks/`](docs/runbooks/README.md) |
| Plain-language explanations of patterns | [`docs/learning/`](docs/learning/README.md) |
| The original brief | [`docs/initial-brief.md`](docs/initial-brief.md) |

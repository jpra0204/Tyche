# Status

*Last updated: 2026-11-17*

## Current phase

**Phase 1: core and backtesting (`US`, end of day). In progress.** Pablo agreed the PR list below on 2026-11-16.

- Phase 0 is merged.
- PR 1 (domain types) is merged.
- PR 2 (event envelope and bus) is merged.
- PR 3 (clock and calendar) is merged.
- PR 4 (workspace and config) is merged; ADR-0017 accepted.
- PR 5 (data port and Parquet cache) is merged.
- PR 6 is merged: 6a directly, 6b through #9 (it first landed on the 6a branch because its stacked base was not retargeted in time).
- PR 7 (engine and replay feed) is open for review against `main`.
- Recommended: turn on *Automatically delete head branches* in the GitHub repository settings, so GitHub retargets stacked PRs by itself.
- Adjusted prices decided 2026-11-17: split-adjusted prices with dividends as cash events ([ADR-0019](docs/adr/0019-split-adjusted-prices-and-cash-dividends.md)).

## What works today

- `uv sync` installs a pinned Python 3.14 environment.
- `make check` passes: ruff lint and format, mypy strict, five import-linter architecture contracts, pytest.
- `tyche --version` runs.
- CI runs the same checks on every pull request and on `main`.
- Domain types (PR 1): `Currency`, `Money`, `Timeframe`, `Instrument`, `Bar`.
- Event bus (PR 2): `Event`, `Envelope`, `EventBus`.
- Clock and calendar (PR 3): `Clock` and `Calendar` ports, `Session`, `SimClock`, and an NYSE calendar backed by `exchange_calendars`.
- Workspace and config (PR 4): `tyche init` creates a private workspace; `tyche config check` validates it and prints the config hash. The CLI is built with Typer.
- Data layer (PRs 5, 6a and 6b): `DataProvider` port, data-quality audit, Parquet cache, read-through provider, dividends and splits, and the Yahoo Finance source. `tyche data fetch` downloads real data into the workspace.
- Engine and replay (PR 7, in review): one run loop for every mode; history replayed session by session with no lookahead; an in-memory journal that traces any event to its cause. Checked end to end, from data source to journal.

There is no trading code yet: no strategies, risk, orders or broker. The engine runs replayed history end to end, but nothing reacts to it yet except the journal. Packages still holding only a docstring: `core.backtest`, `core.improvement`, `core.agents`, `core.risk`, the pipeline stages other than `journal`, `strategies`, and the broker, notifier, LLM, storage and report adapters.

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
| 7 | Engine and replay feed (**in review**) | The run loop, historical replay (`BarEvent`, `DataReadyEvent`), in-memory journal | Also `SessionEvent` (moved from PR 3), `DataQualityEvent`, `RunEvent`, and the `PacedClock` port |
| 8 | Account ledger | `Order`, `Fill`, `Position`, account with settled and unsettled cash per currency, `AccountEvent` | |
| 9 | Costs and settlement | A written, dated summary of IBKR Canada's rules, then commission and slippage models and the share-size rule | Verify: commissions, minimums, fractional shares, cash-account settlement |
| 10 | `SimBroker` | Next-open fills, stops against daily bars, rejections, partial fills, settlement | |

**D. Pipeline, up to the first backtest**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 11 | Universe and screening | Stages 1 and 2 for the `US` profile, with liquidity, price and data-quality filters | |
| 12 | Strategy interface and benchmark | The plugin contract, the signals stage, buy-and-hold | Decide: how a strategy sees price history |
| 13 | Portfolio construction | Several strategies at once, per-strategy budgets, conflict resolution | |
| 14 | Risk gate (pass-through) and execution | `ApprovedPortfolioEvent` with no rules yet, target-to-order diffing, idempotent order ids | |
| 15 | Backtest runner | `tyche backtest`, a run record with config hash and code version, the reserved holdout | Decide: how much recent history to reserve. **Milestone: first end-to-end backtest** |

**E. Measurement**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 16 | Metrics | CAGR, volatility, Sharpe, Sortino, max drawdown, turnover, win rate, exposure, all against the benchmark; golden-file regression test | |
| 17 | Reference validation | Our backtester compared with an independent library on a simple strategy, kept as a regression test | Decide: `backtesting.py` or `vectorbt`, after checking their licences |
| 18 | Example strategies | An ETF trend rotation and a mean-reversion strategy that uses a stop | |
| 19 | Backtest report | HTML or Markdown with charts, a cost-drag section, the data-limits statement | Decide: chart library |

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
| Revised promotion criteria with a paper-versus-backtest tracking threshold, as an ADR for approval | 2 |
| User guide page on what protects a position within a session ([ADR-0015](docs/adr/0015-daily-loss-limit.md)) | 2 |
| Maintenance runbook: update `exchange_calendars` regularly, because unscheduled market closures only appear after a library update | 2 |
| Simulated broker credits distributions as cash at the ex-date, and documents that rule (ADR-0019) | 1 (PR 10) |
| Withholding tax on US dividends paid to a Canadian resident: verify the rate and IBKR's handling, then model it | 2 or 4 |
| Trial registry, holdout and deflated results inside the automated gate | 3 |

## Open decisions

| Decision | Needed by |
|---|---|
| Turn on branch protection for `main` (require a PR and the CI check); a GitHub setting only you can change | Now, recommended |
| Opening an IBKR account and its paper account, if not done yet; approval can take days | Before Phase 2 |
| Scheduler: APScheduler or cron in the container | Phase 2 |
| SQLite migration approach | Phase 2 |

Decisions that belong to a Phase 1 PR are listed in the plan above.

## To verify against current sources (not from memory)

| Fact | Where |
|---|---|
| IBKR Canada commissions, minimums and fractional-share rules | Phase 1, PR 9 |
| Settlement rules for an IBKR Canada cash account | Phase 1, PR 9 |
| ~~yfinance limits, terms and adjusted-price behaviour~~ Done 2026-11-17: personal use only, no documented rate limit, "unadjusted" prices are split-adjusted (ADR-0019) | Phase 1, PR 6 |
| Licences of the candidate reference backtesters | Phase 1, PR 17 |
| Linux wheels for all dependencies on Python 3.14 (Docker) | Phase 2 |
| IB Gateway ports, account-id formats, IBC behaviour, 2FA flow | Phase 2 |
| `claude -p` flags, output format and plan limits | Phase 3 |

## Known issues and risks

The honest notes, with what was agreed for each, are in the [system overview, section 9](docs/architecture/system-overview.md#9-assumptions-and-honest-notes).

## Next

1. Pablo reviews and merges PR 7.
2. Pablo creates his real workspace by following `docs/user-guide/01-installation.md`, then tries `tyche data fetch`.
3. Phase 1, PR 8: account ledger, when Pablo says to start.

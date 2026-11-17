# Status

*Last updated: 2026-11-16*

## Current phase

**Phase 1: core and backtesting (`US`, end of day). In progress.** Pablo agreed the PR list below on 2026-11-16.

- PR 1 (domain types) is open for review. It is stacked on the Phase 0 pull request, which is approved but not yet merged; merge Phase 0 first.
- Next: PR 2, event envelope and bus.

## What works today

- `uv sync` installs a pinned Python 3.14 environment.
- `make check` passes: ruff lint and format, mypy strict, five import-linter architecture contracts, pytest.
- `tyche --version` runs.
- CI runs the same checks on every pull request and on `main`.
- Domain types (PR 1, in review): `Currency`, `Money`, `Timeframe`, `Instrument`, `Bar`.

There is no trading, data or backtesting code yet. Apart from `cli` and `core.domain`, every package under `src/tyche/` contains only a docstring saying what will live there.

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
| 1 | Domain types (**in review**) | `Currency`, `Money`, `Instrument`, `Timeframe`, `Bar` | |
| 2 | Event envelope and bus | Envelope fields, FIFO bus, run to completion, fail closed, an event-log helper for tests | |
| 3 | Clock and calendar | `Clock` and `Calendar` ports, `SimClock`, NYSE calendar adapter, `SessionEvent` | Adds `exchange_calendars` |
| 4 | Workspace and config | `TYCHE_HOME`, `tyche init`, typed config for the `US` profile, config hash | Adds `pydantic`. Decide: CLI framework; where your workspace lives |

**B. Data**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 5 | Data port and Parquet cache | `DataProvider` port, cache that records when data was fetched, quality checks, gap detection against the calendar | Adds `pandas`, `pyarrow` |
| 6 | yfinance adapter | Daily bars with retries and adjusted prices, `tyche data fetch` | Adds `yfinance`. Verify: its limits and terms |

**C. Engine and simulation**

| # | PR | Delivers | Verify or decide in this PR |
|---|---|---|---|
| 7 | Engine and replay feed | The run loop, historical replay (`BarEvent`, `DataReadyEvent`), in-memory journal | |
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
| yfinance limits, terms and adjusted-price behaviour | Phase 1, PR 6 |
| Licences of the candidate reference backtesters | Phase 1, PR 17 |
| Linux wheels for all dependencies on Python 3.14 (Docker) | Phase 2 |
| IB Gateway ports, account-id formats, IBC behaviour, 2FA flow | Phase 2 |
| `claude -p` flags, output format and plan limits | Phase 3 |

## Known issues and risks

The honest notes, with what was agreed for each, are in the [system overview, section 9](docs/architecture/system-overview.md#9-assumptions-and-honest-notes).

## Next

1. Pablo merges the Phase 0 pull request, then reviews and merges PR 1.
2. Phase 1, PR 2: event envelope and bus.

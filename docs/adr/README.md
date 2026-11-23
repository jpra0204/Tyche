# Architecture decision records

One short record per significant decision: the context, the decision, the alternatives and the consequences. An ADR is never rewritten after it is accepted. To change a decision, add a new ADR that supersedes the old one.

**Status values**

- **Accepted (brief)**: decided in [`initial-brief.md`](../initial-brief.md).
- **Accepted (Pablo, date)**: decided by Pablo in conversation.
- **Proposed**: my recommendation, waiting for Pablo's approval.
- **Superseded by ADR-nnnn**.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions as ADRs | Accepted (brief) |
| [0002](0002-python-314-and-uv.md) | Python 3.14, pinned with uv | Accepted (brief) |
| [0003](0003-synchronous-event-bus.md) | A synchronous, deterministic, in-process event bus | Accepted (Pablo, 2026-11-16) |
| [0004](0004-hexagonal-architecture.md) | Hexagonal architecture, enforced by import contracts | Accepted (brief; Pablo, 2026-11-16) |
| [0005](0005-backtest-paper-live-parity.md) | One engine for backtest, paper and live | Accepted (brief) |
| [0006](0006-target-positions-with-optional-stops.md) | Target positions with optional stops; typed risk approval | Accepted (Pablo, 2026-11-16) |
| [0007](0007-python-driven-agents.md) | LLMs out of the trading path; Python-driven agents | Accepted (brief; Pablo, 2026-11-16) |
| [0008](0008-public-code-private-workspace.md) | Public code repository, private workspace | Accepted (Pablo, 2026-11-16) |
| [0009](0009-storage-sqlite-parquet.md) | SQLite for state, Parquet for market data | Accepted (brief) |
| [0010](0010-config-toml-pydantic.md) | TOML config validated by pydantic; layered risk limits | Accepted (Pablo, 2026-11-16) |
| [0011](0011-pandas-at-the-edges.md) | pandas as the only dataframe library, kept at the edges | Accepted (Pablo, 2026-11-16) |
| [0012](0012-money-and-time-types.md) | Decimal for money, UTC for time | Accepted (Pablo, 2026-11-16) |
| [0013](0013-live-trading-gate.md) | The live-trading gate | Accepted (Pablo, 2026-11-16) |
| [0014](0014-git-workflow-and-ci.md) | Branch and pull request workflow with CI | Accepted (Pablo, 2026-11-16) |
| [0015](0015-daily-loss-limit.md) | The daily loss limit is measured close to close | Accepted (Pablo, 2026-11-16) |
| [0016](0016-typer-for-the-cli.md) | Typer for the command-line interface | Accepted (Pablo, 2026-11-17) |
| [0017](0017-config-schemas-at-the-boundary.md) | Config file schemas live in `tyche.config`; the core receives domain objects | Accepted (Pablo, 2026-11-17) |
| [0018](0018-audit-market-data.md) | Market data is audited against the calendar, not trusted or rejected | Accepted (Pablo, 2026-11-17) |
| [0019](0019-split-adjusted-prices-and-cash-dividends.md) | Split-adjusted prices, with dividends as cash events | Accepted (Pablo, 2026-11-17) |
| [0020](0020-cost-and-settlement-model.md) | The cost and settlement model for the US profile | Accepted (Pablo, 2026-11-17) |
| [0021](0021-strategies-see-a-window-handed-in.md) | Strategies see a read-only window of history, handed in at every cycle | Accepted (Pablo, 2026-11-18) |
| [0022](0022-portfolio-targets-as-weights-in-sleeves.md) | Portfolio targets are weights of equity, held in one sleeve per strategy | Accepted (Pablo, 2026-11-18) |
| [0023](0023-execution-sleeves-stops-and-cash.md) | Execution: crossing between sleeves, stops after the entry fills, a rebalance band and a price buffer | Accepted (Pablo, 2026-11-19) |
| [0024](0024-backtest-runner-holdout-and-run-record.md) | The backtest runner: a fixed holdout, candidates in the market profile, and a run record | Accepted (Pablo, 2026-11-19) |
| [0025](0025-metrics-against-the-benchmarks-total-return.md) | Metrics: measured against the benchmark's total return, with a zero risk-free rate | Accepted (Pablo, 2026-11-19) |
| [0026](0026-reference-validation-against-backtesting-py.md) | The backtester is checked against backtesting.py, a test-only dependency | Accepted (Pablo, 2026-11-19) |
| [0027](0027-example-strategies-fixed-in-advance.md) | Two example strategies, with their rules fixed before any backtest | Accepted (Pablo, 2026-11-19) |
| [0028](0028-backtest-report-html-and-cost-drag.md) | The backtest report is one HTML file with matplotlib charts, built from the record | Accepted (Pablo, 2026-11-20) |
| [0029](0029-walk-forward-folds-and-a-train-step.md) | Walk-forward: anchored folds of calendar years, and a train step that keeps the configured parameters until sweeps exist | Accepted (Pablo, 2026-11-20) |
| [0030](0030-parameter-sweeps-trial-count-and-deflated-sharpe.md) | Parameter sweeps: every recorded trial counted, the pick by Sharpe ratio, and a deflated Sharpe ratio | Accepted (Pablo, 2026-11-19) |
| [0031](0031-minimum-viable-capital.md) | Minimum viable capital: a size penalty against a large reference account, Fixed against Tiered | Accepted (Pablo, 2026-11-23) |

## Template

```markdown
# ADR-nnnn: Title

- **Status:** Proposed
- **Date:** YYYY-MM-DD

## Context
What problem or question forced a decision.

## Decision
What we decided, stated plainly.

## Alternatives considered
What else was on the table and why it lost.

## Consequences
What becomes easier, what becomes harder, what we must remember.
```

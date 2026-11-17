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

# ADR-0009: SQLite for state, Parquet for market data

- **Status:** Accepted (brief)
- **Date:** 2026-11-16

## Context

Tyche stores two very different kinds of data. Operational state (orders, fills, positions, the journal, proposals, strategy lifecycle) is small, changes one row at a time and must stay consistent when the process crashes. Market data is large, written in bulk, read in ranges by column and never updated in place. The system must cost nothing and run on one machine.

## Decision

- **SQLite** holds operational state, in one file under the workspace's `state/` folder. It is in the standard library, needs no server and is transactional.
- **Parquet** holds market data, in the workspace's `data/` folder, partitioned by source, timeframe and instrument.
- **DuckDB** is allowed for analysis and reports, because it can query SQLite and Parquet together. It is a read-side tool, not a store of record.
- **The journal is append-only.** Every event is stored in sequence with its cause. Rows are never updated or deleted.
- **Fills store their CAD value** at that day's exchange rate, for the tax export in Phase 4.

Storage is reached through ports. The core defines what it needs to save and load; `tyche.adapters.storage` and `tyche.adapters.data` implement it.

## Alternatives considered

- **PostgreSQL.** More capable, and a server to run, back up and secure. Nothing in the roadmap needs it.
- **Files only (JSON or CSV).** No transactions, so a crash mid-write can leave orders and positions disagreeing.
- **Market data in SQLite.** Workable for daily bars, slow and bulky for intraday.

## Consequences

- Backing up Tyche means copying one folder.
- SQLite allows one writer at a time. Tyche has one process writing, so this fits; the dashboard in Phase 5 will read only.
- Schema changes need migrations. The approach will be chosen when the first table is created in Phase 2.
- The free data source revises adjusted prices over time. The cache will record when each file was fetched so that a backtest can state which snapshot of history it used.

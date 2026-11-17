# ADR-0012: Decimal for money, UTC for time

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

Two kinds of quiet bug are common in trading code.

**Money in binary floating point.** `0.1 + 0.2` is not `0.3` in a float. Over thousands of fills, cash and cost base drift by fractions of a cent, and reconciliation against the broker stops matching exactly. The tax export needs exact CAD values.

**Ambiguous time.** A daily bar stamped at midnight looks as if it was known at the start of the day, which is how lookahead bias gets into a backtest. Naive datetimes (no timezone) also break across daylight-saving changes and between New York and Toronto calendars.

## Decision

**Money**

- Cash, fill prices, commissions, quantities and cost base are `decimal.Decimal`.
- `Money` is an amount plus a currency. Adding two currencies is an error; conversion is an explicit operation with a rate.
- Market data (bar prices, volumes) and analytics (indicators, returns, Sharpe) stay `float`. They are estimates, and float maths is what numeric libraries are built for.
- The crossing point is explicit: when a simulated fill takes a bar price, it is converted to `Decimal` and rounded to the instrument's price increment in one place.

**Time**

- Every timestamp in the core is a timezone-aware UTC `datetime`. Ruff's `DTZ` rules reject naive datetimes in CI.
- The core gets the time only from the `Clock` port.
- A bar's timestamp is the moment it became known, which is its close. A daily bar for a New York session is stamped at that session's closing time, including half days.
- A session date is a plain `date` that only has meaning together with a calendar.
- Conversion to local time (America/Toronto) happens only for display: reports, logs and Discord.

## Alternatives considered

- **Floats everywhere.** Simpler and faster, and what most backtesting libraries do. Acceptable for research, not for a ledger that must match a broker and feed a tax calculation.
- **Integer minor units (cents).** Exact and fast, but awkward with fractional shares, sub-cent prices and FX rates.
- **Exchange-local timestamps.** Readable, and a source of bugs as soon as two markets with different calendars share one account.

## Consequences

- The ledger matches the broker to the cent, or reconciliation reports a real difference.
- `Decimal` is slower than `float`. It is used for a handful of operations per fill, so this does not matter.
- The reference-library comparison in Phase 1 will need a small tolerance, because the reference uses floats.
- "Is this known yet?" becomes a comparison between a bar's timestamp and the clock, which a test can assert.

# ADR-0026: The backtester is checked against backtesting.py, a test-only dependency

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Phase 1, PR 17 checks Tyche's backtester against an independent one, as the brief asks: "Validate the backtester against a reference library ... on a simple strategy, and keep it as a regression test". Unit tests and the golden file (PR 16) check that Tyche does what its authors meant. They cannot catch a rule the authors got wrong in the same way twice, in the code and in the test. An engine written by other people, in another style, can.

The plan named two candidates. Checked on 2026-11-19, from PyPI and the projects' licence files:

| | backtesting.py 0.6.6 | vectorbt 1.2.1 |
|---|---|---|
| Licence | AGPL-3.0 | Apache-2.0 with the Commons Clause (no selling a product built on it; not OSI open source) |
| Installs on Python 3.14 | Yes, 14 packages (bokeh, pandas, numpy) | Yes, about 60 (numba, scipy, scikit-learn, Jupyter widgets, plotly) |
| Model | Event-driven: a strategy's `next()` per bar, market orders at the next open | Vectorised: arrays of signals, sizes and prices |
| Whole shares | Yes | Yes, with `size_granularity` |
| Commission | A number, or a function of size and price | Fixed plus a rate per order |

## Decision

1. **backtesting.py is the reference.** Its model is closest to Tyche's: decide at a close, fill at the next open, whole shares. Its commission can be a function, so IBKR's per-share rate with its minimum fits, and it needs a fraction of vectorbt's dependencies.
2. **It is a development dependency only.** It is in the `dev` group, never imported from `src/`, never shipped with Tyche. A new import-linter contract, "Tyche never imports the reference backtester", fails CI if any module of `tyche` imports it. Used this way, unmodified and not offered to anyone over a network, the AGPL asks nothing of Tyche (my reading, not legal advice).

## Implementation choices made in PR 17, for review there

- **One rule, written twice.** `AboveItsAverage` holds 95% of equity in one instrument while its close is above the mean of its last N closes. It is written once against Tyche's `Strategy` contract and once against backtesting.py's `Strategy` class, each on its own engine's view of history. Neither engine reuses the other's code.
- **Tyche as configured, minus regulatory fees.** The `US` profile's universe rules, the 10% rebalance band, the 2% price buffer, T+1 settlement and IBKR Pro Fixed commissions, all unchanged. Regulatory fees are left out, because backtesting.py's commission function is not told whether an order buys or sells, and the SEC fee is on sales only. They are a few cents an order, and they have their own unit tests.
- **95%, so every order is an entry or a full exit.** backtesting.py does not resize a held position, and Tyche does not resize inside its rebalance band. At 95% of equity, the band is never crossed and the price buffer never shrinks a purchase, so both engines place the same orders.
- **Slippage charged as commission.** backtesting.py's `spread` moves only the entry price; on exit it uses the plain price. That cannot model Tyche's 5 basis points against every fill. The reference commission function adds `shares * price * 0.0005` to every fill, which moves the same cash. Fill prices then differ by exactly the slippage, and the test checks that.
- **IBKR Pro Fixed written again.** The reference commission function is written from the published schedule, independently of `tyche.core.domain.costs`. It uses `Decimal`, so that half-cent amounts round to even as Tyche's do (the commission on 7,235 shares is USD 36.175 before rounding, USD 36.18 after).
- **What is compared.** Every fill's day, side, shares and price. Equity at every session close. Every closed trade's dates and profit. The win rate, total return and maximum drawdown that backtesting.py reports, whose definitions are Tyche's. CAGR, volatility, Sharpe and Sortino computed again with pandas from backtesting.py's equity curve, using Tyche's written conventions: an independent check of Tyche's `Decimal` arithmetic.
- **Tolerances.** A millionth of a dollar for money, 10⁻⁹ for ratios. The two engines do the same sums in `Decimal` and in `float`, so what is left is `float` rounding. The largest difference found is 1.5 × 10⁻¹¹ USD on real data and about 10⁻⁹ USD on a USD 1,000,000 account.
- **Two tests.** In CI: a seeded random walk over three years of the real New York calendar (2021 to 2023), a 20-session average, at USD 10,000 (the USD 1.00 minimum binds) and USD 1,000,000 (the per-share rate binds), 53 round trips each. Opt-in (`uv run pytest -m network`): 19 years of real SPY bars from Yahoo, 2005 to 2023, a 50-session average, USD 10,000, with dividends removed on both sides.
- **The tests can fail.** Before committing, four deliberate mismatches were each tried in turn: a USD 0.99 minimum, no slippage on the reference side, the reference sizing at 94%, and the reference deciding one bar late. Each failed the comparison.

## Checked on real data

SPY from 2005-01-03 to 2023-12-29, Yahoo data without dividends, a 50-session average, USD 10,000:

| | Tyche | backtesting.py |
|---|---|---|
| Sessions | 4,781 | 4,781 |
| Fills | 347 | 347 |
| Closed trades | 173, one still open | 173, one still open |
| Final equity | 15,947.33218346788 | 15,947.33218346788 |
| Largest equity difference at a close | | 1.5 × 10⁻¹¹ USD |

The bars include gaps at the open of −8.3% (24 October 2008) and −10.4% (16 March 2020).

## What this does not check

backtesting.py does not model them, so the comparison cannot check:

- **Dividends.** Checked in Tyche's own simulator tests, and against Yahoo's adjusted close for the benchmark (ADR-0025).
- **T+1 settlement and free riding.** A strategy that never holds more than 95% never waits for cash.
- **Regulatory fees.**
- **The volume cap.** It never binds at these sizes.
- **Stops.** backtesting.py can fill a stop on the bar its entry filled; Tyche places a stop when its entry fills, and it works from the next session (ADR-0023). They disagree by design. A stop comparison would need a strategy whose stop can never be hit on its entry day. PR 18, which adds a strategy with a stop, can revisit this.
- **More than one instrument or sleeve**, crossing between sleeves, and the rebalance band.

## Alternatives considered

- **vectorbt.** Free for this use, but about four times the dependencies (numba, scipy, scikit-learn among them), and its vectorised model needs more mapping to match next-open fills and whole-share sizing from the last close.
- **A hand-written reference in pandas.** No new dependency, but the same author writes both sides, which is what an independent check is meant to avoid.
- **backtrader** (GPL-3.0). Event-driven, but not on the plan's list, and not checked further.
- **Comparing with slippage set to zero on both sides.** Simpler, but it would leave Tyche's slippage unchecked. Charging it as commission keeps it in.

## Consequences

- A change to Tyche's simulator, ledger, costs or metrics that breaks agreement with an independent engine fails CI.
- The AGPL dependency is fenced off: CI fails if Tyche imports it, and it is not in Tyche's runtime dependencies.
- backtesting.py raises a pandas deprecation warning under pandas 3.1. It is ignored narrowly in `pyproject.toml`, with the condition for removing it.
- The comparison checks accounting, not strategy design. The rule it trades is a test fixture, not a strategy for real use. For the record, on SPY from 2005 to 2023 it grew 1.59 times, against 5.69 times for holding SPY with dividends reinvested.

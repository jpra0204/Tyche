# ADR-0005: One engine for backtest, paper and live

- **Status:** Accepted (brief)
- **Date:** 2026-11-16

## Context

A common failure in trading systems is a backtester written separately from the live system. The two drift apart, and the backtest ends up measuring a strategy that the live system does not run. The brief requires backtest, paper and live to run the same code path, with only the clock, the data feed and the broker swapped.

## Decision

There is one engine and one set of pipeline stages. A **mode** is nothing more than the choice of three port implementations, made in `tyche.runtime`:

| Mode | `Clock` | Data feed | `Broker` |
|---|---|---|---|
| Backtest | `SimClock` | Historical replay | `SimBroker` |
| Paper | Wall clock | Live feed | `IBKRBroker` (paper account) |
| Live | Wall clock | Live feed | `IBKRBroker` (live account) |

Rules that keep this true:

- **No stage may ask which mode it is in.** There is no `if backtest:` anywhere in the core. A stage that needs different behaviour gets it from a port.
- **Time comes only from the `Clock` port.** The core never calls `datetime.now()`. In a backtest the clock jumps from one event to the next.
- **A backtest is a client of the engine.** `tyche.core.backtest` builds the three simulated parts, runs the ordinary engine and measures the result. It contains no trading logic of its own.

## Alternatives considered

- **A vectorized backtester** (whole price arrays at once). Much faster, and fine for research, but it is a second implementation of the strategy logic. We use one only as an independent reference to validate ours (brief section 6).
- **Sharing strategies but not execution or risk.** This is the usual compromise, and it leaves the riskiest code (sizing, limits, order handling) untested by backtests.

## Consequences

- Risk rules, order handling and portfolio construction are exercised by every backtest.
- Event-by-event simulation is slower than a vectorized one. For daily bars this is seconds, not hours; parameter sweeps may need parallel processes later.
- **Parity is of code, not of markets.** `SimBroker` fills are a model: it assumes fills at the next open with configured slippage and cannot know real liquidity. IBKR's paper account also simulates fills. Reports will say so, and the difference between simulated and real fills is something paper trading is there to measure.

# Backtest, paper and live parity

## The problem

Many trading systems have two implementations: a fast backtester used for research, and a separate live system. They start out equivalent and drift. The backtest sizes positions one way, the live code slightly differently. A risk rule exists live but not in the backtest. After a few months the backtest is measuring a strategy that the live system does not run, and its numbers mean nothing.

## The idea

Write the trading logic once. Run the same code in all three modes, and swap only the three parts that are different by nature:

| What differs | Backtest | Paper | Live |
|---|---|---|---|
| **Time** | Simulated, jumps between events | Real | Real |
| **Market data** | Replayed from history | Arrives after each close | Arrives after each close |
| **Order handling** | Simulated fills | IBKR paper account | IBKR live account |

Everything else is identical: universe, strategies, portfolio construction, risk, execution logic, journal.

This is hexagonal architecture put to work. Time, data and order handling are ports (`Clock`, the data feed, `Broker`), and a mode is a choice of three adapters. See [Hexagonal architecture](hexagonal-architecture.md).

The clock deserves a closer look, because it is the least obvious of the three. If any code calls the system clock directly, a backtest breaks: the code believes it is today while processing a bar from 2015. So nothing in Tyche's core is allowed to ask the operating system for the time. It asks the `Clock` port. In a backtest the clock is a simple object whose time is set by the engine as it replays history.

## Where it is in Tyche

- The engine, written once: `tyche.core.engine`.
- The simulated parts: `tyche.core.sim` (`SimClock`, replay feed, `SimBroker`).
- The `Broker` port is mostly a contract about events, not methods: a broker consumes submitted `OrderEvent`s and publishes fills and every later status. The only method the rest of the core calls is `account()`, the broker's own record of cash and positions. `SimBroker` keeps that record exactly as IBKR keeps a real one, which is what lets reconciliation (Phase 2) compare Tyche's view with the broker's in every mode.
- The real parts: `tyche.adapters.clocks`, `tyche.adapters.data`, `tyche.adapters.brokers`.
- The choice of mode: `tyche.runtime`, and nowhere else.
- The rule that keeps it honest: there is no `if backtest:` anywhere in the core ([ADR-0005](../adr/0005-backtest-paper-live-parity.md)).

## What it costs, and what it does not give you

- **Speed.** Processing one event at a time is far slower than computing on whole arrays. For daily bars it does not matter. For large parameter sweeps it will, and the answer then is running backtests in parallel, not a second implementation.
- **It is parity of code, not of markets.** The simulated broker *assumes* how orders fill: at the next open, with a configured slippage. Real fills differ. So does IBKR's paper account, which also simulates. Parity guarantees that the logic being tested is the logic that runs. It does not guarantee the backtest's numbers. Every fill rule `SimBroker` assumes is listed in [backtesting internals](../developer-guide/backtesting-internals.md).

That second point is why the roadmap has a paper phase at all. The backtest checks the idea; paper trading checks the machinery and shows how far simulated fills are from the broker's.

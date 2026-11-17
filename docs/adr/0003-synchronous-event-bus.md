# ADR-0003: A synchronous, deterministic, in-process event bus

- **Status:** Proposed
- **Date:** 2026-11-16

## Context

The brief requires an event-driven core where all components communicate through events, and where backtest, paper and live share one code path. It also puts backtest correctness above everything. A backtest is only trustworthy if running it twice gives the same result, event for event.

"Event-driven" is often taken to mean asynchronous: `asyncio`, threads or a message broker. Those add concurrency, and concurrency makes the order of events depend on timing.

## Decision

The core uses a **single-threaded, synchronous, in-process event bus** that we write ourselves.

1. **Publish enqueues.** `bus.publish(event)` appends the event to a FIFO queue and returns. It does not call handlers directly.
2. **Dispatch is a loop.** The engine pops one event at a time and calls its subscribers in the order they were registered. Handlers may publish more events, which join the back of the queue.
3. **Run to completion.** The engine asks the outside world for the next input (the next bar, the next broker message, the next clock tick) only when the queue is empty. Everything caused by one input is fully processed before the next input arrives.
4. **Subscription order is explicit.** Subscribers are registered in one place, the engine's wiring, in a documented order. No handler depends on import order or on priorities scattered through the code.
5. **Fail closed.** An exception in a handler stops the run and raises a halt. A trading system that carries on after an unexpected error is worse than one that stops.
6. **No `asyncio` in the core.** Async vendor libraries (`ib_async`) run their own loop inside the adapter. The adapter turns what it receives into events and hands them to the engine through a thread-safe inbox, which the engine drains as an outside input under rule 3.

## Alternatives considered

- **An `asyncio` bus.** Natural for `ib_async`, but handler interleaving then depends on timing, tests need an event loop, and determinism has to be defended everywhere instead of being free.
- **An external broker (Redis, Kafka, NATS).** Useful when components are separate processes. Here it would add infrastructure, cost and failure modes to a system that runs on one machine.
- **Plain function calls between stages.** Simplest, and fine for a pure end-of-day script. It loses the seams that make the three modes swappable, and the journal would have to be threaded through every call instead of subscribing once.

## Consequences

- The same inputs always produce the same event sequence. Backtests can be regression-tested by comparing event logs (golden files).
- Handlers are ordinary functions; unit tests publish an event and assert on what comes out.
- A slow handler blocks everything. That is acceptable for daily and minute bars. Tick-level trading would need a different design, which is out of scope.
- Run to completion fixes a subtle ordering problem: fills produced by a bar are applied to the account before the decision cycle that the same bar triggers.
- Explained in plain language in [Event-driven design](../learning/event-driven-design.md).

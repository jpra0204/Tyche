# Learning notes

Short, plain-language explanations of the patterns Tyche uses, each tied to the place in the code where it appears. These serve the project's first goal: understanding the design well enough to build it again.

Each note answers the same four questions: what problem does this solve, what is the idea, where is it in Tyche, and what does it cost.

## Available now

| Note | In one sentence |
|---|---|
| [Event-driven design](event-driven-design.md) | Components announce facts instead of calling each other |
| [Hexagonal architecture](hexagonal-architecture.md) | The core defines what it needs; the outside world plugs in |
| [Backtest, paper and live parity](backtest-paper-live-parity.md) | One engine, with the clock, feed and broker swapped |
| [The gated agent loop](gated-agent-loop.md) | LLMs propose, code tests, a human decides |
| [Value objects](value-objects.md) | Small immutable types that cannot hold an invalid value |
| [Config at the boundary](config-at-the-boundary.md) | Check all configuration once, as it enters, and turn it into types that cannot be wrong |
| [Time as a port](time-as-a-port.md) | The core asks a clock and a calendar for the time; it never reads the system clock |
| [Working with unreliable data](unreliable-data.md) | Audit every answer against the calendar, and cache with a record of what was already asked |

## Planned

| Note | Written in |
|---|---|
| Lookahead bias and how the clock prevents it | Phase 1, PR 15 |
| Walk-forward testing and overfitting | Phase 1 |
| Plugins: adding behaviour without changing the core | Phase 1 |
| Property-based testing | Phase 2 |
| Idempotent orders | Phase 2 |
| Reconciliation: trusting the broker over yourself | Phase 2 |
| Schemas as contracts between agents and code | Phase 3 |

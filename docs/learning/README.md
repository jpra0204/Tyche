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
| [Property-based testing](property-based-testing.md) | State a rule, let the computer search for a counter-example |
| [Time as a port](time-as-a-port.md) | The core asks a clock and a calendar for the time; it never reads the system clock |
| [Lookahead bias](lookahead-bias.md) | Why a backtest must never see the future, and how the clock and the replay stop it |
| [Working with unreliable data](unreliable-data.md) | Audit every answer against the calendar, and cache with a record of what was already asked |
| [Costs as data](costs-as-data.md) | Keep broker prices in dated config, use the broker's own formula, and round every doubt against yourself |
| [State built from events](state-built-from-events.md) | A stage remembers only what it has been told, so it cannot see the future and behaves the same in every mode |
| [Plugins](plugins.md) | The core defines a small contract, hands the plugin only what it allows, and checks everything that comes back |
| [Sub-ledgers that add up](sub-ledgers.md) | Each strategy keeps its own book of shares, they must always sum to the real account, and only the difference is traded |
| [The holdout and the run record](holdout-and-run-records.md) | Keep the most recent history away from every experiment, and record every run with its code, config and data |
| [Measuring against a benchmark](measuring-against-a-benchmark.md) | Compare with what simply holding the index paid, dividends reinvested, measured the same way on the same days |
| [Golden-file tests](golden-files.md) | Save every number of a fixed run, and make any change to them a deliberate, reviewed step |
| [Reference validation](reference-validation.md) | Run the same scenario through an engine written by other people, and compare every fill and every close |
| [Strategies without memory](strategies-without-memory.md) | Write each rule so the fact it needs is in the bars, the positions or the broker, never in the strategy object |

## Planned

| Note | Written in |
|---|---|
| Walk-forward testing and overfitting | Phase 1 |
| Idempotent orders | Phase 2 |
| Reconciliation: trusting the broker over yourself | Phase 2 |
| Schemas as contracts between agents and code | Phase 3 |

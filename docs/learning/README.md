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
| [Reports built from the record](reports-from-the-record.md) | The record is the truth; the report is a rebuildable, deterministic view of it |
| [Strategies without memory](strategies-without-memory.md) | Write each rule so the fact it needs is in the bars, the positions or the broker, never in the strategy object |
| [Walk-forward testing and overfitting](walk-forward-testing.md) | Judge a choice only on history it has not seen: train on the past, test on the next year, and move forward |
| [Multiple testing and the deflated Sharpe ratio](multiple-testing.md) | Count every version ever tried, and judge the best against what the best of that many tries reaches by luck |
| [Layered limits](layered-limits.md) | Guardrails above profiles above strategy limits, each only stricter, all checked before anything runs |
| [What account size costs](account-size.md) | Run the same strategy on a large account and on yours, change nothing else, and read the difference as the price of being small |
| [Functional core, imperative shell](functional-core.md) | Put the rules in a pure function of plain values, and keep the wiring in a thin wrapper around it |
| [Circuit breakers and latches](circuit-breakers.md) | Watch the whole account, trip at a limit, and stay tripped until a person resets it; let a person trip it too, with a switch that fails closed |
| [Checkpoints](checkpoints.md) | Save what a run did, whole and checked, when it ends; rebuild what the market says from the cache; prove it by cutting a run in two |
| [Schema migrations and an append-only log](schema-migrations.md) | Number every change to the tables and never edit a shipped one; make every stored row say what it is and how it was written |
| [Notifications outside the trading path](notifications-outside-the-trading-path.md) | Decide what to tell a person as plain values inside the system, send it at the edge after the work, and never let a failed message stop the work; secrets as types, redacted at the last moment |
| [Orders sent at most once](at-most-once-orders.md) | Write down what you send before sending it, look for it after a failure, and never send it twice; keep the vendor's model behind a small translating layer |
| [Catching up without acting on stale signals](freshness-and-catch-up.md) | Replay every missed input so measurements stay right, but act only before the deadline the action must meet; judge freshness by that deadline, not by age |
| [Reconciliation: trusting the broker over yourself](reconciliation.md) | Compare your record with the counterparty's; decide per field what is noise to adopt, what to repair, and what halts; explain a difference, but let a human turn the explanation into a fact |
| [Read, reconcile, then decide](read-then-decide.md) | Take in what the world did and check your record against it before you act; hold an action that could collide with another until the first is confirmed |

## Planned

| Note | Written in |
|---|---|
| Idempotent orders | Phase 2 |
| Schemas as contracts between agents and code | Phase 3 |

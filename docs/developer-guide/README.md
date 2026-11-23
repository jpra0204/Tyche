# Developer guide

For Pablo as a developer, and for any Claude Code session working on the code.

## Available now

| Page | What it covers |
|---|---|
| [Repo map](repo-map.md) | What every folder and package holds, and which way dependencies may point |
| [How to add a data source](how-to-add-a-data-source.md) | Writing a `BarSource` adapter, with yfinance as the worked example |
| [How to add a strategy](how-to-add-a-strategy.md) | The strategy contract in practice: one class, the rules it must keep, testing it without the engine |
| [Conventions](conventions.md) | Coding rules, testing strategy, git workflow, definition of done |
| [Pipeline contracts](pipeline-contracts.md) | What each pipeline stage takes in, promises to put out, keeps between events, and does when something is wrong |
| [Backtesting internals](backtesting-internals.md) | How the replay, the universe rules, what a strategy sees and the simulated broker turn history into fills; how a run is measured; walk-forward, sweeps and minimum viable capital; the known limits |
| [The state database](state-database.md) | `state/tyche.db`: how it is opened, the journal table, adding a migration, and changing an event that is stored |
| [IBKR Canada: costs and settlement](ibkr-canada-costs-and-settlement.md) | Commissions, fractional shares, cash-account settlement and currency conversion, checked against IBKR's pages and dated |

For the end-to-end flow of an event from data to fill, see the [system overview](../architecture/system-overview.md#5-the-event-flow) and the [event catalog](../architecture/event-catalog.md).

## Planned

| Page | What it will cover | Written in |
|---|---|---|
| `how-to-add-a-broker.md` | Implementing the `Broker` port | Phase 2 |
| `how-to-add-a-notifier.md` | Implementing the `Notifier` port | Phase 2 |
| `how-to-add-an-agent.md` | Workflow, schemas, input bundle, tests with a fake `LLMProvider` | Phase 3 |
| `how-to-add-a-market-profile.md` | Instruments, currency, calendar, FX policy | Phase 4 |

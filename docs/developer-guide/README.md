# Developer guide

For Pablo as a developer, and for any Claude Code session working on the code.

## Available now

| Page | What it covers |
|---|---|
| [Repo map](repo-map.md) | What every folder and package holds, and which way dependencies may point |
| [How to add a data source](how-to-add-a-data-source.md) | Writing a `BarSource` adapter, with yfinance as the worked example |
| [Conventions](conventions.md) | Coding rules, testing strategy, git workflow, definition of done |
| [IBKR Canada: costs and settlement](ibkr-canada-costs-and-settlement.md) | Commissions, fractional shares, cash-account settlement and currency conversion, checked against IBKR's pages and dated |

For the end-to-end flow of an event from data to fill, see the [system overview](../architecture/system-overview.md#5-the-event-flow) and the [event catalog](../architecture/event-catalog.md).

## Planned

| Page | What it will cover | Written in |
|---|---|---|
| `pipeline-contracts.md` | Input and output contract of each pipeline stage, with examples | Phase 1, extended in Phase 2 |
| `how-to-add-a-strategy.md` | One file plus config, with no core changes | Phase 1 |
| `backtesting-internals.md` | Fill rules, cost models, how lookahead is prevented, known limits | Phase 1 |
| `how-to-add-a-broker.md` | Implementing the `Broker` port | Phase 2 |
| `how-to-add-a-notifier.md` | Implementing the `Notifier` port | Phase 2 |
| `how-to-add-an-agent.md` | Workflow, schemas, input bundle, tests with a fake `LLMProvider` | Phase 3 |
| `how-to-add-a-market-profile.md` | Instruments, currency, calendar, FX policy | Phase 4 |

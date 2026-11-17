# ADR-0004: Hexagonal architecture, enforced by import contracts

- **Status:** Accepted (brief) for the pattern; **Proposed** for the package layout and contracts
- **Date:** 2026-11-16

## Context

The brief requires a ports-and-adapters structure: the core depends on interfaces (`DataProvider`, `Broker`, `Notifier`, `LLMProvider`, `Clock`, `Calendar`), never on concrete vendors. It also wants to add brokers, data sources and markets without rewriting the core.

A rule like "the core never imports a vendor" erodes unless something checks it. One convenient import in a hurry is enough.

## Decision

**Layout.** Four top-level areas inside `src/tyche/`:

| Area | Contains | May import |
|---|---|---|
| `core` | Domain, events, ports, pipeline stages, risk, engine, simulator, backtester, improvement loop, agent workflows | Standard library and pure libraries only |
| `adapters`, `strategies`, `config` | Vendor and I/O code; built-in strategy plugins; config loading | `core` |
| `runtime` | The composition root that wires adapters into the core | Everything below it |
| `cli` | The `tyche` command | Everything below it |

**The dividing line is purity, not origin.** Code that does no I/O and reads no wall clock belongs in the core even when it implements a port. That is why `SimBroker`, `SimClock` and the historical replay feed live in `tyche.core.sim`, while the wall clock and the Parquet cache are adapters.

**Enforcement.** Five import-linter contracts in `pyproject.toml` run in CI:

1. Outer layers depend inward, never the reverse.
2. Inside the core, dependencies point toward the domain.
3. The core never imports a vendor or I/O library.
4. No LLM code in the trading path.
5. Strategies cannot reach risk, execution, the engine or any port.

Ports are `typing.Protocol` classes, so an adapter does not need to inherit from anything in the core.

## Alternatives considered

- **Layout by technical type** (`models/`, `services/`, `utils/`). It says nothing about which way dependencies may point.
- **Convention only, no enforcement.** Cheaper today, but the rule would decay without anyone noticing.
- **Separate installable packages for core and adapters.** The strongest boundary, but heavy for a single-developer project. The import contracts give most of the benefit.

## Consequences

- Adding a broker, data provider or notifier means adding one adapter and one line of wiring. The how-to guides in the developer guide will follow that shape.
- The contracts are deliberately coarse while the packages are empty. Contract 2 in particular will be adjusted as real code shows where dependencies need to go; each change is reviewed in a PR.
- The full folder map is in the [repo map](../developer-guide/repo-map.md). Explained in plain language in [Hexagonal architecture](../learning/hexagonal-architecture.md).

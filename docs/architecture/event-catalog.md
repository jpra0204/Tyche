# Event catalog

*Status: Phase 0 design, awaiting Pablo's review. Field lists show the important fields, not final signatures; those are fixed when each event is implemented and this page is updated in the same PR.*

Every component in the trading path communicates through the events on this page. The bus and its ordering rules are described in [ADR-0003](../adr/0003-synchronous-event-bus.md).

## Conventions

- **Events are immutable facts.** An event says something happened ("this bar closed", "this order was filled"). It is never edited after it is published.
- **Names end in `Event`** and are in the past or present tense of a fact, not a command.
- **All timestamps are timezone-aware UTC** ([ADR-0012](../adr/0012-money-and-time-types.md)). A bar's timestamp is the moment the bar became known (its close), which is what makes lookahead visible in code.
- **Events carry domain objects** (`Instrument`, `Money`, `Order`), never dataframes or vendor objects.

## The envelope

Every event has these fields in addition to its own:

| Field | Meaning |
|---|---|
| `seq` | Position in the run's event sequence, assigned by the bus. Deterministic, so two runs of the same backtest can be compared event by event. |
| `occurred_at` | Time from the `Clock` port when the event was published. Simulated time in a backtest. |
| `cycle_id` | The decision cycle this event belongs to, if any. Fills and stop triggers that arrive between cycles have none. |
| `caused_by` | `seq` of the event that led to this one. Following these links answers "why did this order exist?". |
| `source` | Name of the component that published it. |

## Two patterns used below

**Batch marker.** When a stage must wait for a group of events (all bars for a timestamp, all strategies' signals), the publisher sends the items and then one `...ReadyEvent`. Consumers act on the marker, not on a count or a timer. This is what lets daily and intraday bars share one code path.

**Proposed versus approved.** Portfolio construction publishes a *proposed* target. The risk gate is the only component that can publish an *approved* one, and execution subscribes only to the approved type. The types make the bypass impossible.

## Catalog

### Market data and time

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `SessionEvent` | Engine (from `Clock` and `Calendar`) | Broker, risk, scheduler | `calendar`, `session_date`, `kind` (open or close), `is_half_day` | 1 |
| `BarEvent` | Data feed | Broker (to fill waiting orders and check stops), market-data store | `instrument`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `is_adjusted` | 1 |
| `DataReadyEvent` | Data feed | Universe (starts a decision cycle) | `timeframe`, `as_of`, `instruments`, `missing` | 1 |
| `DataQualityEvent` | Data feed, data adapters | Journal, notifier | `instrument`, `kind` (gap, stale, suspect value, fetch failed), `detail` | 1 |

### Decision cycle (pipeline stages 1 to 5)

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `UniverseEvent` | Universe | Screening | `as_of`, `eligible`, `excluded` (each with a reason) | 1 |
| `ScreeningEvent` | Screening | Signals | `as_of`, `ranked` (instrument, score, screen name) | 1 |
| `SignalEvent` | Signals (one per strategy) | Portfolio construction | `strategy_id`, `strategy_version`, `as_of`, `targets` (instrument, weight within the strategy's budget, optional `stop_price`, `reason`) | 1 |
| `SignalsReadyEvent` | Signals | Portfolio construction | `strategies` reported, `failed` (strategy and error) | 1 |
| `TargetPortfolioEvent` | Portfolio construction | Risk gate only | `as_of`, `targets` (instrument, quantity, optional `stop_price`, contribution per strategy), `conflicts_resolved` | 1 |
| `RiskEvent` | Risk gate | Journal, notifier | `rule`, `scope` (order, position, strategy, account), `action` (shrink, block, flatten, halt), `before`, `after`, `profile` | 2 |
| `ApprovedPortfolioEvent` | Risk gate only | Execution | `as_of`, `targets`, `profile`, `adjustments` (the `RiskEvent`s applied) | 1 (pass-through gate), 2 (real rules) |

### Orders, fills and account state (stages 6 and 7)

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `OrderEvent` | Execution (created, submitted), broker (every later status) | Broker, account state, journal | `order_id`, `client_order_id` (idempotency key), `instrument`, `side`, `quantity`, `order_type` (market, stop), `time_in_force`, `status`, `reason` | 1 |
| `FillEvent` | Broker | Account state, journal | `order_id`, `quantity`, `price`, `commission`, `currency`, `fx_rate_to_cad` | 1 |
| `AccountEvent` | Account state | Risk, reconciliation, journal | `cash` per currency (settled and unsettled), `positions`, `equity`, `peak_equity` | 1 |
| `FxConversionEvent` | Broker | Account state, journal | `from`, `to`, `amount`, `rate`, `cost` | 4 |
| `ReconciliationEvent` | Reconciliation | Engine (halts on mismatch), journal, notifier | `status` (match or mismatch), `differences` | 2 |

`OrderEvent.status` follows one lifecycle. One event is published per transition:

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Submitted
    Created --> Rejected: failed a pre-trade check
    Submitted --> Accepted
    Submitted --> Rejected
    Accepted --> PartiallyFilled
    Accepted --> Filled
    Accepted --> Cancelled
    Accepted --> Expired
    PartiallyFilled --> Filled
    PartiallyFilled --> Cancelled
    Filled --> [*]
    Rejected --> [*]
    Cancelled --> [*]
    Expired --> [*]
```

The `client_order_id` is derived from the decision that created the order (cycle, instrument, side, purpose), so sending the same decision twice produces the same id and the broker adapter can drop the duplicate.

### System

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `RunEvent` | Engine, scheduler | Journal, notifier | `run_id`, `mode`, `kind` (started, completed, failed, skipped), `reason`, `config_hash`, `code_version` | 1 |
| `HaltEvent` | Risk (drawdown), reconciliation, kill switch | Engine, execution, notifier | `cause`, `flatten`, `resume_requires` (always a manual step) | 2 |

## What is deliberately not an event

- **Agent activity.** Research notes and proposals are files in the workspace, not events. Agents run offline and have no access to the bus.
- **Notifications.** The notifier subscribes to the events above and formats messages. There is no `NotificationEvent`, so nothing can ask the notifier to say something that did not happen.
- **Configuration changes.** Config is loaded and validated once at startup. Changing the risk profile or a strategy's state is a CLI command that writes to the database and takes effect on the next run; it is recorded in the journal as an audit entry.

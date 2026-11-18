# Event catalog

*Status: Phase 0 design, accepted by Pablo on 2026-11-16. Field lists show the important fields, not final signatures; those are fixed when each event is implemented and this page is updated in the same PR. Implemented so far: the envelope, the bus, `SessionEvent`, `BarEvent`, `DataReadyEvent`, `DataQualityEvent`, `RunEvent`, `OrderEvent`, `FillEvent`, `DistributionEvent`, `UniverseEvent` and `ScreeningEvent` (marked **implemented** below). Each other event is added by the PR that first publishes it.*

Every component in the trading path communicates through the events on this page. The bus and its ordering rules are described in [ADR-0003](../adr/0003-synchronous-event-bus.md).

## Conventions

- **Events are immutable facts.** An event says something happened ("this bar closed", "this order was filled"). It is never edited after it is published.
- **Names end in `Event`** and are in the past or present tense of a fact, not a command.
- **All timestamps are timezone-aware UTC** ([ADR-0012](../adr/0012-money-and-time-types.md)). A bar's timestamp is the moment the bar became known (its close), which is what makes lookahead visible in code.
- **Events carry domain objects** (`Instrument`, `Money`, `Order`), never dataframes or vendor objects.

## The envelope

An event holds only its own facts: which bar, which order. The bus wraps every published event in an `Envelope` and fills in the delivery details, so the component that creates an event cannot get them wrong. Handlers receive the envelope and read the event from `envelope.event`.

| Field | Set by | Meaning |
|---|---|---|
| `seq` | The bus | Position in the run's event sequence, starting at 1. Events are handled in this order, and two runs of the same backtest can be compared event by event. |
| `occurred_at` | The bus, from the clock | Time when the event was published, in UTC. Simulated time in a backtest. |
| `source` | The publisher | Name of the component that published it. Inside a handler it defaults to that subscriber's name. |
| `caused_by` | The bus | `seq` of the event whose handler published this one. Empty for an input from outside, such as a bar from the feed. Following these links answers "why did this order exist?". |
| `cycle_id` | Whoever starts a cycle | The decision cycle this event belongs to, if any. Everything published while handling an event inherits that event's cycle. Fills and stop triggers that arrive between cycles have none. |
| `event` | The publisher | The event itself. |

Causation is automatic. A handler calls `bus.publish(SomeEvent(...))` and nothing else; the bus knows which event is being handled and records it as the cause.

## Rules the bus enforces

From [ADR-0003](../adr/0003-synchronous-event-bus.md), implemented in `tyche.core.events.bus`:

| Rule | What happens otherwise |
|---|---|
| An event class is a frozen dataclass whose name ends in `Event` | `TypeError` when the class is defined (name) or first published (not frozen) |
| `publish` only queues; `drain` delivers until the queue is empty | Calling `drain` from inside a handler is an error |
| Subscribers run in registration order, and a subscription covers subclasses | Subscribing to `Event` receives everything; this is how the journal works |
| Subscriptions close at the first publish | A late `subscribe` raises, so no subscriber can miss the start of a run |
| An input from outside must name its source | `publish` raises |
| A handler that raises halts the bus for good | `HandlerError`; nothing still queued is delivered |
| One drain may not exceed a set number of events | `RunawayDispatchError` and a halt; this catches handlers publishing to each other in a loop |

## Two patterns used below

**Batch marker.** When a stage must wait for a group of events (all bars for a timestamp, all strategies' signals), the publisher sends the items and then one `...ReadyEvent`. Consumers act on the marker, not on a count or a timer. This is what lets daily and intraday bars share one code path.

**Proposed versus approved.** Portfolio construction publishes a *proposed* target. The risk gate is the only component that can publish an *approved* one, and execution subscribes only to the approved type. The types make the bypass impossible.

## Catalog

### Market data and time

Within one moment, the feed's inputs come in a fixed order: session open, then any `DistributionEvent` going ex (at the open), then each instrument's `BarEvent`, then any `DataQualityEvent` for the day, then session close, then `DataReadyEvent`. The bus finishes everything each input causes before the next one (ADR-0003), so a decision cycle always sees every bar and every fill from that moment.

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `SessionEvent` | Feed (in a backtest, `HistoricalReplay` from the `Calendar`) | Broker, risk, scheduler | `session` (calendar, day, open and close times, half day), `phase` (open or close) | **implemented** (PR 7) |
| `BarEvent` | Feed, at the bar's own timestamp | Broker (to fill waiting orders and check stops), universe (keeps the last few bars), market-data store | `bar` (instrument, timeframe, timestamp, prices, volume, `adjustment`) | **implemented** (PR 7) |
| `DataReadyEvent` | Feed, after every bar for the decision time | Universe (starts a decision cycle: publishes one `UniverseEvent`) | `timeframe`, `as_of`, `delivered`, `missing` | **implemented** (PR 7) |
| `DataQualityEvent` | Feed (from each `DataIssue` in a `BarHistory`: at its session's close, or before the first session if it has none) | Journal, notifier, universe (excludes the instrument for a few cycles after a disqualifying issue) | `issue` (instrument, `DataIssueKind`, session day, detail) | **implemented** (PR 7) |

### Decision cycle (pipeline stages 1 to 5)

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `UniverseEvent` | Universe, once per `DataReadyEvent` | Screening, journal | `as_of`; `eligible`: `UniverseMember`s (instrument, `last_close`, `average_dollar_volume`); `excluded`: `Exclusion`s (instrument, `ExclusionReason`, `detail`). Every instrument the feed expected appears exactly once. The reasons, in the order they are checked: `not_in_profile`, `no_bar`, `data_issue`, `insufficient_history`, `price_too_low`, `illiquid` | **implemented** (PR 11) |
| `ScreeningEvent` | Screening, once per `UniverseEvent` | Signals, journal | `as_of`, `screen` (its name), `ranked`: `ScoredInstrument`s (instrument, `score`), best first, ties broken by symbol; `cut`: eligible instruments below the screen's limit | **implemented** (PR 11) |
| `SignalEvent` | Signals (one per strategy) | Portfolio construction | `strategy_id`, `strategy_version`, `as_of`, `targets` (instrument, weight within the strategy's budget, optional `stop_price`, `reason`) | 1 |
| `SignalsReadyEvent` | Signals | Portfolio construction | `strategies` reported, `failed` (strategy and error) | 1 |
| `TargetPortfolioEvent` | Portfolio construction | Risk gate only | `as_of`, `targets` (instrument, quantity, optional `stop_price`, contribution per strategy), `conflicts_resolved` | 1 |
| `RiskEvent` | Risk gate | Journal, notifier | `rule`, `scope` (order, position, strategy, account), `action` (shrink, block, flatten, halt), `before`, `after`, `profile` | 2 |
| `ApprovedPortfolioEvent` | Risk gate only | Execution | `as_of`, `targets`, `profile`, `adjustments` (the `RiskEvent`s applied) | 1 (pass-through gate), 2 (real rules) |

### Orders, fills and account state (stages 6 and 7)

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `OrderEvent` | Execution (created, submitted), broker (every later status) | Broker, account state, journal | The `OrderState`: the `Order` (`client_order_id` as idempotency key, `instrument`, `side`, `quantity`, `order_type` market or stop, `stop_price`, `time_in_force` day or GTC, `reason`), its `status`, `filled_quantity` and `note` (the reason for a rejection, cancellation or expiry). Domain types built in PR 8. `SimBroker` ignores a repeated `client_order_id` | **implemented** (PR 10) |
| `FillEvent` | Broker, just before the order's new status | Account state, journal | The `Fill`: `fill_id`, `client_order_id`, `instrument`, `side`, `quantity`, `price`, `commission` (commission plus regulatory fees, ADR-0020), `filled_at`, `trade_date`, `settles_on`. No `cycle_id`: fills arrive between cycles. The CAD exchange rate for tax is added in Phase 4 | **implemented** (PR 10) |
| `AccountEvent` | Account state | Risk, reconciliation, journal | A snapshot of the `Account` (cash per currency, settled and unsettled; positions at average cost; marks; realised profit). Peak equity is the risk layer's to track (Phase 2). Domain type built in PR 8. Moved from PR 10 to PR 14, where execution first needs Tyche's own view of the account | 1 (PR 14) |
| `DistributionEvent` | Data feed (from the `CashDistribution`s in a `BarHistory`), at the open of the ex-date session | Broker (credits cash to holders at the previous close), journal | `distribution`: a `CashDistribution` (`instrument`, `ex_date`, `amount_per_share`, `kind`) | **implemented** (PR 10) |
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
    PartiallyFilled --> PartiallyFilled: another partial fill
    PartiallyFilled --> Filled
    PartiallyFilled --> Cancelled
    PartiallyFilled --> Expired: a day order at the close
    Filled --> [*]
    Rejected --> [*]
    Cancelled --> [*]
    Expired --> [*]
```

The `client_order_id` is derived from the decision that created the order (cycle, instrument, side, purpose), so sending the same decision twice produces the same id and the broker adapter can drop the duplicate.

### System

| Event | Published by | Consumed by | Key fields | Phase |
|---|---|---|---|---|
| `RunEvent` | Engine, scheduler | Journal, notifier | `run_id`, `mode`, `stage` (started or completed), `code_version`, `config_hash`. A failed run cannot publish (the bus has halted), so the engine reports failure in its `RunResult`; a skipped run comes with the scheduler (Phase 2) | **implemented** (PR 7) |
| `HaltEvent` | Risk (drawdown), reconciliation, kill switch | Engine, execution, notifier | `cause`, `flatten`, `resume_requires` (always a manual step) | 2 |

## What is deliberately not an event

- **Agent activity.** Research notes and proposals are files in the workspace, not events. Agents run offline and have no access to the bus.
- **Notifications.** The notifier subscribes to the events above and formats messages. There is no `NotificationEvent`, so nothing can ask the notifier to say something that did not happen.
- **Configuration changes.** Config is loaded and validated once at startup. Changing the risk profile or a strategy's state is a CLI command that writes to the database and takes effect on the next run; it is recorded in the journal as an audit entry.

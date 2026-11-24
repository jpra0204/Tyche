# Orders sent at most once

**The pattern:** when a message might or might not have arrived, choose in advance which mistake you can live with. Write down what you are about to send *before* sending it. After a failure, look for it on the other side before doing anything else. If it is not there, do not send it again.

## Why it matters here

Every networked system meets the same question. Tyche sends an order to IB Gateway, and the connection drops before the answer comes back. Did the order arrive? There is no way to know from Tyche's side alone. There are only three ways to deliver a message over an unreliable link:

| Delivery | How | The mistake it allows |
|---|---|---|
| **At most once** | Send; never resend | A message lost for good |
| **At least once** | Resend until confirmed | The same message twice |
| **Exactly once** | At least once, plus a receiver that recognises and drops duplicates | None, but only if the receiver really does deduplicate |

For an order, a duplicate means buying twice: real money, perhaps double the risk Tyche allowed. A lost order means missing a trade until the next day's decision, which sizes from what the account really holds. Pablo chose **at most once** (ADR-0042). Exactly once would need IBKR to refuse a second order with the same `orderRef`, and IBKR's documentation does not promise that.

## The three pieces

1. **An idempotency key.** Every order carries Tyche's own id, derived from the decision that made it (`client_order_id`, sent as IBKR's `orderRef`). The same decision always gives the same id, so the adapter can recognise it, and so can IBKR's lists.
2. **A write-ahead record.** The order is written to the state database, and committed, *before* it is sent (`broker_order`, fate `sending`). If Tyche crashes between sending and the answer, the record survives, and the next run knows this order may be out there. Databases use the same idea for their own crash safety: write the intention to the log, then do it.
3. **Look before acting.** After reconnecting, `sync` searches IBKR's open orders, today's completed orders and today's executions for every order whose fate is unknown. Found: track it. Not found: mark it lost and never send it again.

A smaller rule rides along: **deliver, then record.** `sync` lets every subscriber handle an event before the store notes that it was published. If something fails in between, the run saves no checkpoint, and the next run sees the event again. That is at-least-once *inside* Tyche, where a duplicate is harmless because the ledger refuses a fill it has already applied.

## An anti-corruption layer

`IBKRBroker` never touches `ib_async`'s objects. It talks to a small `IBClient` protocol in plain, typed records (`ReportedOrder`, `ReportedExecution`), and `IbAsyncClient` translates. The vendor's model stops at that line, so:

- the rules that matter (identity, at-most-once, status mapping) are tested against a fake gateway, including connections lost before and after an order arrives;
- a change in `ib_async` touches one translation file;
- the same protocol could sit in front of another library, or IBKR's web API, without the adapter's rules changing.

## In Tyche

- [ADR-0042](../adr/0042-ibkr-paper-adapter-at-most-once-orders.md): the decision; [ADR-0041](../adr/0041-orders-and-identity-at-ibkr.md): the facts.
- `src/tyche/adapters/brokers/ibkr/broker.py`: sending, `sync`, never resending.
- `src/tyche/adapters/brokers/ibkr/client.py`: the protocol and its records.
- `src/tyche/adapters/storage/broker_orders.py` and `migrations/0003_broker_order.sql`: the write-ahead record.
- `tests/adapters/brokers/ibkr/fake_gateway.py`: a gateway that can drop the connection on cue.

## What it costs

- A missed trade when the connection drops at the worst moment. Rare, visible (the order is rejected with a note, and the paper run alerts), and limited to one day.
- One commit before every order: a few milliseconds, a handful of times a day.
- A second table that changes in place, beside the append-only journal. The journal still records every change, as events.

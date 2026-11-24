# Reconciliation: trusting the broker over yourself

**The pattern:** keep two independent records of the same thing, yours and the counterparty's, and compare them at fixed moments. Decide in advance, field by field, which differences are noise you take from the counterparty, which you can explain and repair, and which mean you no longer understand your own state. Stop on the last kind, and never guess your way out of it.

Banks call this *reconciliation*: matching your ledger against the bank statement line by line. Every trading system needs it, because the broker's record is the one that money actually follows.

## Why it matters here

Tyche keeps its own view of the account (`AccountState`), the sleeve book and the working orders, all saved in the checkpoint at the end of each run. IBKR keeps its own. They should agree, because Tyche builds its view from the fills IBKR reports. They will not always:

- a run did not happen, and IB Gateway only returns **today's** executions, so a stop that fired yesterday is invisible except as fewer shares;
- IBKR cancels resting stops by itself, at every quarter's end among other times;
- IBKR holds a dividend as *accrued* until it pays it, perhaps net of withholding, while Tyche credits it at the ex-date;
- a run failed after sending an order, so its state was never saved;
- someone traded the account by hand.

If Tyche decides on a record that is wrong, every order after that is sized on fiction. A purchase sized on cash that is not there is refused; a sale sized on shares that are not there would be a short sale.

## Three answers, chosen per field

The useful design work is not the comparison, which is a few dictionary lookups. It is deciding, before any data arrives, what each kind of difference means (ADR-0044):

| Field | Rule | Why |
|---|---|---|
| Positions | Exact | Whole shares: any difference is a fact Tyche missed |
| Orders | Exact, except one that ended with no shares moved | A stop IBKR cancelled is harmless and will be re-placed; halting each quarter would teach Pablo to ignore halts |
| Cash | Take the broker's, within a tolerance plus dividends on their way | Fees, interest and dividend timing make exact cash impossible, and the broker decides what an order can buy |

**Adopting the counterparty's figure** is the important move for cash. Tyche does not try to model every fee and interest posting. It compares, accepts a small gap, and from then on uses the broker's number. The gap is recorded, so drift is visible in the journal, but it never accumulates.

## Explain, but do not apply

When a position differs by exactly what one missing order would have done, the explanation is almost certain: it filled on a day no run read. The price is not known, but the cash that moved gives it. Tyche still halts. It records the explanation and lets `tyche resume` apply it after Pablo has looked. An inferred fill is a guess with good odds, and the cost of being wrong is a ledger that no longer matches reality, silently. A human glance is cheap by comparison.

This is the same line ADR-0042 drew for the IBKR adapter: report what today's records cannot explain, never guess. Reconciliation is the place with enough context to *explain*. Only Pablo may turn an explanation into a fact.

## Halt through the state, not an event

A reconciliation halt is stored in the checkpoint and handed to the risk gate when it is built, as the drawdown halt is. Every approval then carries it, so the approval stays the one place that says what may be traded. Execution needs no second input to combine (no `HaltEvent`). The same reasoning made the kill switch and the drawdown halt ride on the approval.

## Test it where you know the answer

In a backtest, Tyche's records and the simulator's come from the same ledger, so they must reconcile as a match, whatever was working when the run ended. That is a free, strong test: `tests/integration/test_reconciliation.py` runs two years of three sleeves and reconciles at four awkward moments. If the comparison ever reports a difference there, the comparison is wrong, not the data.

## In Tyche

- [ADR-0044](../adr/0044-reconciliation-exact-positions-broker-cash.md): the rules, and the four choices Pablo made.
- `src/tyche/core/pipeline/reconciliation/compare.py`: `reconcile`.
- `src/tyche/core/pipeline/reconciliation/correct.py`: `correct` after each check, `resolve` for `tyche resume`.
- `src/tyche/core/domain/reconciliation.py`: `BrokerRecord`, `Reconciliation`, `ReconciliationState`.
- `src/tyche/adapters/brokers/ibkr/broker.py`: `IBKRBroker.record()`.
- [Reconciliation mismatch runbook](../runbooks/reconciliation-mismatch.md).

Related: [checkpoints](checkpoints.md), [orders sent at most once](at-most-once-orders.md), [circuit breakers](circuit-breakers.md), [state built from events](state-built-from-events.md).

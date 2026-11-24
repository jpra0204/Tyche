# ADR-0044: Reconciliation: exact positions and orders, the broker's cash

- **Status:** Proposed
- **Date:** 2026-11-24

## Context

The brief's pipeline stage 7: *on startup and after every run, compare internal state with the broker's. If they disagree, stop trading and alert.* Tyche keeps its own record of the account (`AccountState`, [ADR-0023](0023-execution-sleeves-stops-and-cash.md)), the sleeve book and execution's working orders, all saved in the checkpoint at the end of every run ([ADR-0038](0038-checkpoints-across-restarts.md)). The broker keeps its own. Phase 2, PR 13 compares them.

Earlier decisions left four questions here:

- **Tolerances.** The plan said commissions are only known after a fill. That is no longer the gap: `IBKRBroker` holds every execution back until IBKR's commission report for it arrives ([ADR-0042](0042-ibkr-paper-adapter-at-most-once-orders.md)). The real gaps are in cash. Tyche credits a dividend as cash at the ex-date ([ADR-0019](0019-split-adjusted-prices-and-cash-dividends.md)); IBKR reports it as `AccruedDividend`, "dividends accrued but not paid", until it pays it, perhaps net of withholding (TWS API, *Account Updates*, read 2026-11-24; the page does not say whether the accrual is gross or net, nor in which currencies it is reported). IBKR accrues interest monthly (`AccruedCash`), which Tyche does not model, and does not say whether its commission report includes regulatory fees ([facts page](../developer-guide/ibkr-orders-and-paper-account.md)).
- **Missed fills.** IB Gateway returns only the current day's executions. A fill on a day no run read cannot be read later; ADR-0041 left it to reconciliation to rebuild it from positions and cash, or halt.
- **Stops IBKR cancels by itself**: at the end of the calendar quarter after the one the order was placed in, after 90 days without a login, after some corporate actions ([ADR-0041](0041-orders-and-identity-at-ibkr.md)). Every resting stop meets the first within about six months.
- **How a reconciliation halt reaches execution.** The event catalog planned a `HaltEvent`. The drawdown halt and the kill switch chose instead to ride on the gate's approval ([ADR-0035](0035-account-rules-and-the-drawdown-halt.md), [ADR-0039](0039-kill-switch-and-manual-restart.md)).

Pablo decided all four on 2026-11-24, before any code: **positions and orders exact, cash taken from the broker within a tolerance**; **the halt stored, read by the gate, lifted only by `tyche resume`**; **a missed fill halts, and `tyche resume` applies it when exactly one order explains it**; **an order gone at the broker with no shares moved is corrected without a halt**.

## Decision

1. **One pure comparison.** `reconcile(checkpoint, broker, tolerances, at)` in `tyche.core.pipeline.reconciliation` compares a `Checkpoint` (Tyche's account view, the sleeve book, execution's working orders, the last reconciliation's memory) with a `BrokerRecord`, and returns a `Reconciliation`. `Broker.record()` gives the record: the broker's `Account`, every Tyche order it lists as working with its remaining shares, the number of working orders in the account that are not Tyche's, dividends accrued and not paid per currency, and anything the adapter could not settle (an execution awaiting its commission, a correction). `SimBroker` and `IBKRBroker` both implement it. The paper run (PR 14) reconciles at startup after `sync`, and again after the run, each time on a checkpoint, never on stages in the middle of a run.

2. **Positions are exact.** Whole shares per instrument, no tolerance. Cost and marks are not compared: IBKR prices positions its own way.

3. **Orders are exact, with one correction.** Every order Tyche expects working must be listed by the broker with the same remaining shares, and the broker must list no working order Tyche does not expect, its own or anyone's. An expected order the broker no longer lists, on an instrument whose position matches, **ended with no shares moved**: a stop IBKR cancelled, a market-on-open order that did not trade. Reconciliation removes it from Tyche's records (the working order, and the sleeve's resting stop) and carries on. The next decision re-places a stop the sleeve still wants: execution already brings every sleeve's stop in line with what it wants at each decision.

4. **Cash comes from the broker, within a tolerance.** For each currency Tyche trades in (the profile's cash currencies), Tyche's total cash, settled and pending, is compared with the broker's total cash plus its accrued dividends. The gap allowed is:

   - `cash_tolerance`, a new required table `[reconciliation]` in `config/markets/<NAME>.toml`, `cash_tolerance = "1.00"` in the profile's cash currency: fees and interest Tyche does not model; plus
   - the dividends Tyche credited since the last reconciliation, and the dividends the broker reported accrued at the last reconciliation: a dividend on its way, at whatever withholding.

   Within it, Tyche **adopts the broker's cash**: settled cash becomes the broker's settled cash plus its accrued dividends, pending cash the broker's settlement schedule. The broker decides what an order can buy, so its figure is the one to size on. The adjustment is recorded in the `Reconciliation`. Beyond it, the gap is a difference.

5. **A missed fill is explained, never applied by itself.** For an instrument whose position differs, if exactly one expected order is missing from the broker's list, on the right side, with exactly the missing shares, it filled on a day no run read. Its price is unknown: it is taken from the cash gap, `gap ÷ shares`, commission folded in, and only when it is the only such order in its currency (two would share one gap). This `InferredFill` explains the difference, but the reconciliation is still a mismatch: trading halts, and the alert says what `tyche resume` would apply.

6. **A mismatch halts, stored in the checkpoint.** Any difference left unexplained, any inferred fill, or anything the adapter could not settle makes the `Reconciliation` a mismatch. The checkpoint's new `reconciliation` memory holds it as `halt`, with nothing else changed. The risk gate is built with it, as with the drawdown halt, and every approval carries it as `unreconciled`, with no targets: execution keeps every holding and sends nothing; resting stops stay (plan note `unreconciled`). **A kill-switch flatten is not executed under it**: Tyche's holdings are exactly what is in doubt, and a sale sized on them could try to sell shares the account does not hold. The runbook says to flatten in IBKR's own apps instead. No `HaltEvent`: the approval stays the whole truth about what may be traded.

7. **Only `tyche resume` lifts it.** `tyche resume` lists the mismatch as it lists the drawdown halt. Lifting it applies what the halt explained: each inferred fill to the account, the sleeves it served (pro rata to what the order owed each, a stop to its own sleeve) and execution's working orders, then the broker's cash as recorded, then any ended orders. Differences the halt could not explain are Pablo's to fix in the account by hand first. The next run reconciles again at startup, so anything still different halts again.

8. **Every check is journaled.** `ReconciliationEvent` carries the `Reconciliation`: status (`match`, `corrected`, `mismatch`), differences, inferred fills, ended orders and each currency's cash check. `AlertCollector` alerts on a mismatch and on ended orders; adopting cash is routine and is not alerted (the daily summary, PR 16, will show it).

9. **Backtests reconcile too.** `SimBroker.record()` makes the same comparison possible in a backtest, where both records come from the same ledger: a reconciliation at the end of a backtest is a `match`, and the tests check it.

## Alternatives considered

- **A single cash tolerance.** Every dividend would exceed any tolerance small enough to mean anything, once at the ex-date and again at the pay date. Pablo chose against it.
- **Tyche keeps its own cash and only alerts.** Leaves Tyche sizing purchases on cash the broker may not have (a dividend not yet paid, fees not modelled), and lets the two records drift apart for good.
- **Exact cash.** A halt around every dividend and every interest posting: halts nobody would read after the first month.
- **A `HaltEvent`.** Execution would combine two inputs, and the approval would no longer say everything that may be traded. ADR-0035 and ADR-0039 chose against it for the same reason.
- **A clean reconciliation lifts the halt by itself.** No manual step, but a difference that comes and goes would never be looked at. Pablo chose against it.
- **Apply an inferred fill without halting.** Convenient after a missed day, but its price is inferred and the day unknown. Pablo chose to see it first.
- **Never infer.** Pablo would have to trade the account back to Tyche's records (buy back shares a stop sold) before resuming.
- **Halt on a stop IBKR cancelled.** A manual resume every quarter end, with the position unprotected until then. Pablo chose the correction.

## Consequences

- A workspace created before PR 13 must copy `[reconciliation]` from a new one; Tyche refuses to start without it. The config hash changes.
- The checkpoint gains `reconciliation` (last check's time, Tyche's dividends received and the broker's accrued dividends then, and any halt). Checkpoints saved before it read back with an empty memory.
- `ApprovedPortfolioEvent` gains `unreconciled`; `PlanNote` gains `unreconciled`; `ResumeEvent` gains `reconciliation`. `ReconciliationEvent` replaces the planned row in the event catalog, and `HaltEvent` is dropped.
- Adopted accrued dividends count as settled cash, as Tyche's ledger already treats a dividend from its ex-date. A purchase could then count on a dividend IBKR has not paid; IBKR refuses what settled cash cannot pay, and execution's price buffer covers amounts of this size.
- An inferred fill's day is unknown: it is recorded on the day of the check, which shifts its realised profit and its settlement by the days missed. Its commission is folded into its price.
- The first paper run has no Tyche record to compare: PR 14 must start Tyche's view from the broker's record, or from an empty account against an empty one.
- Currencies the profile does not trade (a CAD balance in a CAD-based account) are not compared until Phase 4.
- Two more paper checks: in which currencies `AccruedDividend` is reported, and whether it is gross or net of withholding. If it is reported only in the base currency, a dividend's payment may exceed the allowance and halt once; then this rule is revisited.
- Reconciliation finds what a failed run left at the broker (ADR-0038): an order it sent is one the broker lists and Tyche does not expect, so it halts, and Pablo cancels it by hand.

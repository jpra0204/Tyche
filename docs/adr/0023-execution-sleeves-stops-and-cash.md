# ADR-0023: Execution: crossing between sleeves, stops after the entry fills, a rebalance band and a price buffer

- **Status:** Accepted (Pablo, 2026-11-19)
- **Date:** 2026-11-19

## Context

Execution (Phase 1, PR 14) is where approved weights of equity become whole shares and orders ([ADR-0022](0022-portfolio-targets-as-weights-in-sleeves.md)). Two questions were left open for it by the plan, and two more appeared while designing it:

1. **When is a protective stop placed?** With its entry, it protects the entry session, but a same-day stop-out sells shares before their purchase settles: free riding, and a 90-day settled-cash restriction in the live account ([ADR-0020](0020-cost-and-settlement-model.md)). After the entry fills, the entry session has no stop.
2. **How is a netted fill split between sleeves?** Orders are netted across sleeves (ADR-0022), so one fill can serve several sleeves, or a partial fill too few.
3. **What about small resizes?** A weight of equity is a moving number of shares. Two sleeves at 0.6 SPY and 0.4 QQQ would be resized by a share or two almost every day, each trade paying the USD 1.00 minimum commission.
4. **What if the open is higher than the close?** Orders are sized at the close and fill at the next open. A fully invested purchase that no longer fits in settled cash at the open is cancelled whole, as IBKR would reject it, so buy-and-hold at 1.0 would fail on most days the market opens up.

## Decision

1. **A stop is placed when its entry fills, and works from the next session.** When a purchase fills, each sleeve that asked for a stop gets one good-till-cancelled stop order for all its shares of that instrument. In a backtest it starts working at the next session's open. A stop can then never sell shares bought the same day, so it can never free-ride. The entry session is unprotected; a gap down the next morning still fills at the open (ADR-0006).
2. **Wishes cross between sleeves first, then the rest is netted, and fills are split pro rata.** At a decision, shares one sleeve gives up and another wants move between them in the sleeve book at the last close, with no order and no commission. What does not cross becomes one market order per instrument, serving only the sleeves on its side. A fill of that order, partial or full, is split in proportion to what each of those sleeves is still owed, in whole shares, with leftover shares going to the largest remainders and ties to the earlier strategy id. Account totals stay exact; per-strategy attribution is approximate by one night's price move.
3. **A held position is resized only outside a rebalance band.** If a sleeve's target for an instrument is within `rebalance_band` of what it holds, as a fraction of the target, the holding is kept as it is. Entries (nothing held) and exits (a target of zero) always trade. The band is set per market profile, in `[execution]` of `config/markets/<NAME>.toml`; the `US` default is `"0.10"` (10%). It is a modelling choice: reports state it, and the parameter sweeps (PR 21) can test it.
4. **Purchases must be payable at the last close plus a price buffer.** A cycle's purchases together must fit the account's buying power at the next open, costed at the last close times `1 + price_buffer`, with slippage, commission and fees. If they do not, they shrink. The buffer is set in `[execution]` too; the `US` default is `"0.02"` (2%). It binds only when cash is short, so a fully invested sleeve holds about 2% in cash. A larger gap still cancels the purchase, and the next cycle tries again.

## Implementation choices made in PR 14, for review there

These follow from the decisions above and from ADR-0006 and ADR-0022. They are recorded here so that they are visible, and can be changed in review.

- **Sizing.** `whole_shares(equity × weight, last close)`, rounding down, with equity from Tyche's own account view at the same close. A positive weight worth less than one share is a target of zero, and the plan says so.
- **Purchases shrink in proportion.** When the cycle's purchases do not fit, each is scaled by cash over cost and rounded down; while they still do not fit (minimum commissions do not scale), the largest is cut one share at a time. Inside one instrument, the cut is shared between sleeves pro rata, as for a partial fill. Rounding down can leave a little cash unspent.
- **Cash that counts.** Buying power is settled cash as it will be at the next session's open, minus purchases not yet settled (`CashBalance.buying_power`). A sale's proceeds therefore pay for purchases from the session after it settles, as ADR-0020 decided. The simulated broker uses the same rule at each open. Before this, two purchases at one open could each pass the check and spend the same cash.
- **Order of orders.** Sales first, then stop changes, then purchases. One market order per instrument per decision; day orders, so each fills or expires by the next decision.
- **Stops are kept in line at every decision.** A sleeve's resting stop must have the price the strategy asked for and cover the shares it holds, less any it is selling at the next open. Otherwise it is cancelled and placed again; if the sleeve no longer wants one, it is cancelled. Shares still to be bought get their stop when they fill.
- **Cancellation is an event.** Execution publishes `CancelRequestEvent`; the broker cancels the order if it is still open and ignores the request if it has finished.
- **Order ids come from the decision.** `<decision time>-<symbol>.<exchange>-<side>` for a market order, `<decision time>-<symbol>.<exchange>-stop-<strategy>` for a stop placed at a decision, `<fill id>-stop-<strategy>` for a stop placed after a fill. A decision handled once is not handled again.
- **What execution refuses (fail closed, ADR-0003).** A decision with no account snapshot from the same close, a market order still open at a decision, or sleeves that do not add up to the account's positions halt the run. A run starts with cash only.
- **What it reports.** One `ExecutionPlanEvent` per decision, before its orders: for each sleeve and instrument, what it held, its target, what crossed, what was ordered, and why the plan differs from its weight (kept, within the band, below one share, cash-limited).
- **Tyche's own account view.** `AccountState` applies the same fills, settlements and distributions as the broker, to the same ledger, and publishes an `AccountEvent` at every session close. Phase 2 reconciliation compares it with the broker's own record.
- **The risk gate passes everything.** `PassThroughGate` publishes each proposed portfolio as approved, with profile `"pass-through"`. The `RiskEvent`s that explain changes arrive with the rules in Phase 2.

## Alternatives considered

- **Place the stop with its entry.** Protects the first session, but a same-day stop-out is a free-riding violation in the backtest and a 90-day restriction live.
- **Fixed priority between sleeves** for fills and cuts. Simpler, but the same strategy would always absorb partial fills and cash shortfalls, and an exact crossing would still need a rule.
- **Trade to the exact target every cycle.** What fixed budgets literally mean, but it pays the minimum commission on one-share trades, and strategies cannot avoid it.
- **Let the simulator shrink a purchase to the cash at the open.** Fully invested, but the backtest would do something the live account cannot ([ADR-0005](0005-backtest-paper-live-parity.md)).

## Consequences

- The first end-to-end backtest (PR 15) can run: every order comes from an approved portfolio, and the sleeve book gives each strategy its own positions.
- Buy-and-hold at 1.0 ends up about 98% invested, and does not trade again unless its holding drifts more than 10% from its target. Reports must state both parameters next to the results.
- A stop-out on the entry session cannot happen in a backtest. Live, the same holds as long as execution places the stop only after the fill report.
- Every workspace's `config/markets/US.toml` needs the `[execution]` table.
- Per-strategy results (PR 16) are approximate where sleeves cross: shares change sleeve at the decision's close, not at the next open.

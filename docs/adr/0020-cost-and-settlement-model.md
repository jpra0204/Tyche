# ADR-0020: The cost and settlement model for the US profile

- **Status:** Accepted (Pablo, 2026-11-17)
- **Date:** 2026-11-17

## Context

PR 9 had to replace remembered numbers with checked ones before any cost model is written. The facts, with sources, are in [IBKR Canada: costs and settlement](../developer-guide/ibkr-canada-costs-and-settlement.md), checked on 2026-11-17. Four of them shape the model:

1. **The minimum commission dominates.** Under IBKR Pro Fixed an order costs USD 0.005 a share, at least USD 1.00, at most 1% of its value. Every order a sub-USD 1,000 account places pays the minimum or the cap: 0.5% to 1% per side.
2. **IBKR's API cannot place fractional orders.** Tyche will trade through the API, so it can hold whole shares only.
3. **US trades settle T+1, and a cash account buys with settled cash only.** IBKR's pages are not fully consistent on that second point.
4. **Selling a position before its purchase settles is free riding**, and puts the account on settled-cash-only trading for 90 days.

A backtest that ignores any of these would report results the live account cannot reproduce.

## Decision

1. **Commissions follow IBKR Pro Fixed exactly**, as published on 2026-11-17: `min(max(0.005 × shares, 1.00), 1% × value)` in USD, per order. Regulatory fees are added as published: the SEC fee on the value of sales, FINRA's audit-trail fee per share, and FINRA's trading-activity fee per share sold. The rates live in the `US` profile's config with the date they were checked, not in code.
2. **Tiered is not modelled yet.** Its total cost depends on exchange fees that vary by venue and are not known before execution. PR 22 (minimum viable capital) will compare Fixed with Tiered under a stated exchange-fee assumption, and Pablo chooses the plan for the real account from that.
3. **Whole shares only.** Order sizing rounds a target down to whole shares. A target worth less than one share is dropped, and the run records it, so a report can say how much of the intended portfolio could not be held.
4. **Settlement is T+1 on the exchange calendar.** A trade on session *d* settles on the next session.
5. **Purchases use settled cash only.** This is the stricter of IBKR's two statements. Sale proceeds from session *d* can fund a purchase on session *d*+1 at the earliest. A rotation that sells and buys at the same open therefore takes two sessions.
6. **Free riding is recorded, not prevented.** A sale of shares before their purchase has settled is executed, as the real broker would, and counted as a violation in the run. Reports show the count. With rule 5 in place, the 90-day restriction would change nothing in the simulation, so the count is the signal: any non-zero count is a design problem to fix in the strategy or its stops.
7. **Slippage is a modelling assumption, not a fact.** Fills move against the order by a configurable number of basis points of the fill price. The proposed default is 5 basis points per side. Reports state the value used. PR 20 or 21 adds a sensitivity check (zero and double).
8. **Not modelled in Phase 1:** currency conversion (the `US` profile holds USD only), GST or PST on commissions (not verified to apply), and the overnight-order minimum rule (Tyche's orders are day orders for the next open).

## Alternatives considered

- **Fractional shares in backtests.** Better allocation for a small account and lower minimum-share effects, but live trading through the API could not reproduce it. A backtest that holds what live cannot is the exact gap parity exists to close ([ADR-0005](0005-backtest-paper-live-parity.md)).
- **Buy with unsettled proceeds, as the free-riding FAQ's examples suggest.** Faster rotations. Rejected for now because IBKR's buying-power FAQ says the opposite, and a wrong guess shows up as rejected orders in live trading. If the paper account in Phase 2 shows unsettled proceeds are spendable, a new ADR can relax rule 5.
- **Prevent free riding in the simulator** by refusing same-day sales. It would hide the problem: a real stop order at the broker will execute regardless. Recording it keeps the backtest honest about what the live account would do.
- **A flat percentage cost per trade.** Simple, but it hides the minimum commission, which is the dominant cost at this account size.

## Consequences

- The cost drag of a small account appears in every backtest, at its real size. Some strategies that look good gross of costs will not survive; that is the point.
- Rotations are slower by one session in a cash account. A strategy that relies on same-open rotation must say so and will be measured with the delay.
- A protective stop placed on the day of entry can cause a free-riding violation if it triggers that same day. PR 10 (`SimBroker`) and PR 18 (the mean-reversion strategy with a stop) must show how often this happens. A possible fix, decided then, is to place the stop from the session after entry.
- Cost and settlement rules are pure functions in `tyche.core.sim`, with no I/O, configured from the profile. The rates carry a "checked on" date and must be re-checked before Phase 2 and before going live.
- Two facts remain unverified and are recorded on the facts page: whether unsettled proceeds are spendable in an IBKR Canada cash account, and whether GST or PST applies to commissions. Both are checked in Phase 2.

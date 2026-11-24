# ADR-0041: Orders and account identity at IBKR

- **Status:** Accepted (Pablo, 2026-11-24)
- **Date:** 2026-11-23

## Context

PR 11 builds `IBKRBroker`, the first adapter that talks to a real broker. Before it does, PR 10 checked the facts it depends on against IBKR's and the library's current pages: [IBKR: the API, orders and the paper account](../developer-guide/ibkr-orders-and-paper-account.md), read on 2026-11-23. Eight of them shape the adapter:

1. **A port proves nothing.** IB Gateway defaults to 4002 for paper and 4001 for live, but either can be set to any port. `ib_async`'s README uses 4001, the live default, in its example. The gateway sends the session's account numbers on connection.
2. **IBKR documents no account-number format.** The `DU` prefix for paper accounts comes from third-party guides only.
3. **A market-on-open order (`MKT` with time in force `OPG`) joins the opening auction** on the primary listing exchange. A day market order only becomes active after the opening print. The simulator fills at the session's open price.
4. **IBKR cancels GTC orders by itself**: at the end of the quarter after the one they were placed in, after 90 days without a login, after a split or a large or special dividend. US-stock stops trigger only in regular hours, and are not lowered for ordinary dividends.
5. **`orderId` must strictly increase and persists across sessions.** `orderRef` is described as a lifetime tag in one place and as "intended for institutional customers only" in another. An API order can be changed only by the client id that placed it.
6. **IB Gateway returns executions only since midnight of the current day**, and completed orders only for the day.
7. **The gateway resubmits by default** orders it received while its own connection to IBKR was down.
8. **The paper account never settles trades at a clearing house**, so it cannot answer whether a cash account may buy with unsettled proceeds. IBKR's FAQs still disagree on that.

Two more facts do not shape the adapter but need a decision. Adding `ib_async` 2.1.0 (already named in [ADR-0002](0002-python-314-and-uv.md)) lowers `tzdata` from 2026.6 to 2025.3 through its `<2026.0` bound. And FINRA's Trading Activity Fee comes back on 2027-01-01 at USD 0.000195 a share sold, while the cost template still holds the holiday's zero.

## Decision

1. **Identity is the account id, compared exactly.** On connection the paper adapter reads the account list the gateway sends. It refuses to continue unless that list is exactly the configured `IBKR_ACCOUNT_ID`. It does not infer paper or live from a prefix or a port. The port is always given explicitly from `.env`, never taken from a library default. This is [ADR-0013](0013-live-trading-gate.md)'s account check, made concrete.
2. **Orders for the next open are market-on-open orders**: `MKT`, time in force `OPG`, SMART-routed, sent after the close. If the paper account shows that MOO orders for stocks are refused or behave unlike the pages say (check 2 on the facts page), PR 11 uses day market orders instead and records the difference from the simulator in the backtesting internals.
3. **Protective stops are sell `STP` orders, `GTC`, regular hours only** (`outsideRth` false), as the simulator assumes with daily bars. **Tyche never assumes a stop is still resting.** At every run, the stops it expects are compared with the broker's open orders (reconciliation, PR 13), and the paper cycle (PR 14) re-places a stop that IBKR cancelled by itself, saying so in the run's report.
4. **Every order carries Tyche's own key in `orderRef`**, made from the run id and a counter, and Tyche records the `orderId` and `permId` the broker gives it. Tyche connects with one fixed client id from `.env`, never client id 0, and never calls `reqGlobalCancel`, which would cancel Pablo's own orders too. If check 6 shows `orderRef` does not survive a reconnection, the stored `permId` is the key instead. **Tyche never resends an order whose fate it does not know**: it reads open orders, the day's completed orders and executions first. How a resend after a lost connection is recognised as a duplicate is still PR 11's decision.
5. **The day's fills are read the same day.** The run after the close reads that day's executions. When a run did not happen, the missed fills cannot be read from the gateway; reconciliation (PR 13) rebuilds them from positions and cash, or halts. The catch-up rule (PR 12) and reconciliation decide how.
6. **The settled-cash rule stays** ([ADR-0020](0020-cost-and-settlement-model.md), rule 5). Paper cannot settle it. Before going live, Pablo asks IBKR Canada support in writing whether a cash account can buy with unsettled sale proceeds, and the answer is added to the costs page. Only a written answer, or the live account's own behaviour, can relax the rule, through a new ADR.
7. **The FINRA fee in the cost template becomes USD 0.000195 a share sold in PR 11**, with its test fixture. Before 2027-01-01, the zero was the right figure for trades on those days. A backtest applies one rate to all its history, and for that history the normal rate is the better figure. The USD 9.79 per-trade cap is not modelled: it binds only above about 50,000 shares sold in one trade. Pablo changes his own workspace's `config/costs/US.toml` himself.
8. **`tzdata` follows `ib_async`'s bound.** PR 11 accepts `tzdata` 2025.3 rather than overriding a library's declared constraint, once it has checked that no release since changed New York's or Toronto's rules. The bound is lifted when `ib_async` releases one that allows 2026. PR 11's tests run on Python 3.14, because `ib_async`'s own CI does not run its tests there.

## Alternatives considered

- **Treat the gateway port, or a `DU` prefix, as the paper check.** Simple, but a port is a setting, and the prefix is not documented by IBKR. A wrong guess here sends paper orders to a live account. Comparing the exact id needs no guess.
- **Day market orders for the open.** They work, but they fill after the opening print at whatever the book offers then, not in the auction the simulator models. Kept as the fallback in decision 2.
- **Limit-on-open orders**, to cap the price. Better protection against a gap, but an order that does not fill leaves the target unreached, and the simulator has no rule for it. Worth a later ADR if opening gaps prove costly.
- **Good-til-date stops**, renewed by Tyche every run. They would avoid IBKR's own cancellations at the quarter's end. But every renewal is a modification, which IBKR treats as a cancel and a new order, and could cost a minimum commission when a stop is moved ([costs page](../developer-guide/ibkr-canada-costs-and-settlement.md)). GTC with a check at every run gets the same safety with fewer messages.
- **Client id 0, to see every order on the account.** It would also bind Pablo's manual orders to Tyche, and an API client could then cancel them. A fixed client id keeps Tyche's orders and his apart.
- **Override `tzdata`'s bound with uv.** Keeps the newest time-zone data, but runs `ib_async` outside the range its authors declare. Tyche records times in UTC ([ADR-0012](0012-money-and-time-types.md)) and reads the exchange calendar from `exchange_calendars`. What changed between the two `tzdata` releases was not checked; PR 11 checks it before accepting the older one, and overrides the bound only if a change affects New York or Toronto.

## Consequences

- PR 11 has a checked basis for every IBKR call it makes, and a short list of checks to run on the paper account before relying on it: the facts page, section 10.
- A paper account needs a funded live account. Until Pablo's live account has a deposit, the paper checks and PR 11's opt-in integration tests cannot run; the adapter is still built and tested against a fake.
- Stops need watching. A stop IBKR cancelled at a quarter's end, or after a corporate action, leaves a position unprotected until the next run puts it back. The daily run is the watch, so a run that does not happen also means a stop that is not checked.
- A missed run loses the gateway's record of that day's fills. That makes the scheduler (PR 15) and reconciliation (PR 13) matter more, not less.
- The kill-switch runbook can now give the Client Portal steps for cancelling one order, and must warn that IBKR Mobile's **Cancel Orders** cancels every working order, the protective stops included.
- The settlement question stays open until IBKR support answers in writing. It is now Pablo's action, before going live.

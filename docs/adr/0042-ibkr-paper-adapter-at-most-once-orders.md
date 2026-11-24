# ADR-0042: The IBKR paper adapter: orders sent at most once

- **Status:** Accepted (Pablo, 2026-11-24)
- **Date:** 2026-11-24

## Context

PR 11 builds `IBKRBroker`, the `Broker` port on IB Gateway, for the paper account. [ADR-0041](0041-orders-and-identity-at-ibkr.md) fixed the facts it rests on: the exact account id as identity, market-on-open orders, GTC stops checked every run, `orderRef` plus the stored `permId`, settled cash only. It left one question to this PR: **how a resend after a lost connection is recognised as a duplicate.**

The danger is concrete. Tyche sends an order; the socket to the gateway drops before the gateway's answer arrives. The order may have reached IBKR or not. Sending it again could buy twice; not sending it could miss a trade. IB Gateway also resubmits by default orders it received while its own link to IBKR was down ([facts page, section 2](../developer-guide/ibkr-orders-and-paper-account.md#2-ib-gateway-ports-sessions-and-restarts)).

Building the adapter raised further questions that needed a rule: how the adapter remembers what it sent across restarts, when IBKR's answers become Tyche's events, what to do with what today's records cannot explain, and how to read cash for a cash account. Facts read for them on 2026-11-24 are in [section 12 of the facts page](../developer-guide/ibkr-orders-and-paper-account.md#12-read-for-pr-11).

## Decision

1. **Orders are sent at most once.** Decided with Pablo on 2026-11-24, before any code. When the fate of a sent order is unknown, the adapter looks for it, after reconnecting, in IBKR's open orders, today's completed orders and today's executions, by `orderRef` (which carries the client order id). Found, it is tracked from there. **Not found, it is rejected with a note saying so, never sent again**, and the next decision sizes from what the account really holds. A duplicate is impossible; the worst case is one missed day. The paper run (PR 14) alerts on it.
2. **A write-ahead record.** Every order is written to the state database, and committed, before it is sent: migration `0003_broker_order.sql`, table `broker_order`, with a `fate` of `sending`, `placed` or `lost`, the broker's `orderId` and `permId` once known, whether Tyche asked to cancel it, and the latest `OrderState` Tyche published. So a crash between sending and the answer still leaves the order known. A client order id already in the table is never sent again, by this run or a later one.
3. **The bus speaks only after IBKR does.** Sending publishes nothing; the order stays `SUBMITTED` until `sync`, called by the paper cycle, reads IBKR and publishes `ACCEPTED`, each `FillEvent` and the order's later statuses, as `SimBroker` does. An order refused before sending (fractional shares, a buy stop, a stop not in whole cents, a symbol whose IBKR spelling is unchecked, no checked connection) is rejected at once with a note starting `not sent:`.
4. **Deliver, then record.** `sync` publishes each event and drains the bus before the store records it, in a second table `broker_fill` for executions (append-only). If any subscriber fails, the run saves no checkpoint ([ADR-0038](0038-checkpoints-across-restarts.md)) and the next run sees the event again. Recording first would lose it. So `sync` runs between drains, never inside a handler.
5. **What today's records cannot explain is reported, not guessed.** An order IBKR no longer lists with no execution today (a stop IBKR cancelled at a quarter's end, a fill from a day no run read), `Filled` at IBKR with fewer shares in today's executions, an unknown status, a corrected execution: each is listed in `sync`'s report for reconciliation (PR 13). No event is invented for it.
6. **An execution waits for its commission.** A `Fill` carries its commission, so an execution is published only once IBKR's commission report for it has arrived; later executions of the same order wait with it, to keep their order. The commission must be in the trade's currency, or the run stops.
7. **IBKR's statuses map to Tyche's lifecycle** as follows. `PendingSubmit` and `ApiPending` change nothing. `PreSubmitted`, `Submitted`, `PendingCancel`, `PreCancelled` and `ApiUpdate`, or any execution, accept the order. `Cancelled`, `ApiCancelled` and `Inactive` cancel an order that worked, or that Tyche asked to cancel, and reject one that never worked. `Filled` is reached through executions only.
8. **The account as IBKR reports it** is settled cash now and by settlement date from the `SettledCashByDate` account value, per currency, plus IBKR's positions and prices (`Account.reported`). Without that value, or with a position in an instrument Tyche does not know, `account()` fails rather than guess.
9. **Contracts are identified by IBKR, not guessed.** Stocks are routed `SMART` by `conId`. The listing exchange's IBKR code is given only where IBKR's documentation was read for it: `ARCA` for `ARCX`. Any other listing (QQQ, TLT and IEF on `XNAS`) is looked up without one and must match exactly one stock contract, or the order is not sent.
10. **The adapter does not import the config package.** It declares the four settings it needs (`GatewaySettings`); `tyche.config.IbkrConnection`, read and checked from `.env`, provides them. Client id 0 is refused.

## Alternatives considered

- **Resend once under the same `orderRef`** when the order is not found. The trade goes out on time, but if the gateway still held the first one without listing it (its resubmission setting), the account would buy twice. Pablo chose against it.
- **Halt and ask Pablo** whenever an order's fate is unknown. Safest, but every dropped connection would need him; at-most-once already rules out a duplicate.
- **Publish `ACCEPTED` as soon as the order is sent**, like `SimBroker`. Simpler, but it would claim IBKR had accepted an order it may never have seen.
- **Record before delivering.** Then a run that fails after the record would lose the event for good: the next run starts from the earlier checkpoint and would never see it again.
- **Mark an order IBKR no longer lists as cancelled.** Wrong when it filled on a day no run read; reconciliation can tell from positions, the adapter cannot.
- **`TotalCashValue` for cash.** It counts unsettled proceeds, which a cash account may not spend ([ADR-0020](0020-cost-and-settlement-model.md)). `SettledCashByDate` gives both.
- **A table of IBKR exchange codes from memory** (`NASDAQ`, `NYSE` and so on). Against the rule that external facts are checked; a wrong code only refuses an order, but a guessed one would sit in the code as if checked.

## Consequences

- A lost connection while sending costs at most one day's trade and never a double one. The paper run must alert on it (PR 14).
- The state database gains two tables. `broker_order` rows change as orders move, unlike the journal; the journal still records every change as events.
- The paper cycle (PR 14) must call `sync` between drains, read its report, and halt or alert on anything it lists; reconciliation (PR 13) gets `account()`, `sync`'s report and the store to compare with Tyche's own view.
- Four new paper checks (8 to 11 on the facts page): contract lookup for the `XNAS` funds, `SettledCashByDate` on paper, the commission's currency on a CAD-based account, and what `Inactive` means in practice.
- `ib_async` 2.1.0 is a dependency, and it lowers `tzdata` to 2025.3. Checked on 2026-11-24: no IANA release since 2025c changed `America/New_York` or `America/Toronto` (ADR-0041, decision 8).

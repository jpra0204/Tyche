# The paper run

`tyche paper run` runs one decision cycle on your IBKR **paper** account: it reads what happened since the last run, checks Tyche's records against IBKR's, decides on the sessions that closed since, and sends the orders for the next open. Design: [ADR-0045](../adr/0045-the-paper-cycle.md).

> **Written in Phase 2, PR 14, and tested against a fake IB Gateway only.** The first run on your real paper account is yours to make. Until the scheduler (PR 15) exists, you run it by hand, once each evening.

## What it needs

- **IB Gateway running and logged in to the paper account**, the one in `IBKR_ACCOUNT_ID`. Tyche refuses any other account.
- **`.env` with all four `IBKR_` keys** (`IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_ACCOUNT_ID`). `uv run tyche config check` says which are set.
- **On the first run, an account holding only cash in USD.** No position and no working order, Tyche's or yours: Tyche cannot tell which strategy owns a position or which stop protects it. How USD gets into the paper account is still your decision (STATUS, *Open decisions*).
- **A risk profile that can trade at the account's size.** `default` holds five positions of 20%; for a small account use one of the stage profiles ([risk profiles](08-risk-profiles.md)).
- **Network access to Yahoo Finance**: the run fetches the session's bars through the cache, two hours after the close.

## Run it

1. Wait until at least **two hours after the close** (18:00 New York, 23:00 UTC in winter). Before that, the session's bars do not count as final and the run only checks the account.
2. Run:

   ```bash
   uv run tyche paper run --risk-profile stage-1
   ```

   Or from the console: **Paper**, choose the profile, **Run the paper cycle…** ([the console](11-the-console.md)). It runs this same command and shows the same output.

3. **Expected**, on a first run with a decision:

   ```text
   First paper run: Tyche started from IBKR's cash.
   Check paper-20261125T233000Z-check: reconciliation match.
   Decision paper-20261125T233000Z:
     Sessions read: 2026-11-25
     Decided at the close of 2026-11-25
     Reconciliation after the run: match
   Saved: checkpoint of run paper-20261125T233000Z.
   Discord: 0 alerts sent.
   ```

   The orders it decided are at IBKR as **market-on-open** orders for the next session. Look at them in Client Portal: **Trade**, then **Orders & Trades**.

## What one run does

1. **The check** (`…-check` in the state database): connects, reads IBKR's fills since the last run, places the stop of each entry that filled, compares Tyche's records with IBKR's, and saves.
2. **The decision**, only if a session has closed since the last decision: fetches the bars, decides, sends the orders, waits up to a minute for IBKR to confirm any stop it cancels (a sale never goes out beside a stop on the same shares), compares with IBKR again, and saves.
3. **The alerts**, after both, to Discord ([which alerts](09-discord-alerts-and-logs.md#what-is-sent-and-when)).

Running it again the same evening is safe: there is no new session, so it only checks the account.

## When it stops

| You see | What it means | Do |
|---|---|---|
| `the IB Gateway connection needs …` | A key is missing from `.env` | Add it; see `.env.example` |
| `IB Gateway is logged in to … account(s), not exactly the one in IBKR_ACCOUNT_ID` | The gateway is on another account, or several | Log the gateway in to the paper account only |
| `the first paper run needs an account holding nothing but cash` | The paper account holds a position or a working order | Close it in IBKR's app, then run again |
| `the paper account holds no USD cash` | The account has only CAD | Decide how USD reaches it (STATUS, *Open decisions*) |
| `Reconciliation … mismatch` | Tyche's records and IBKR's differ; trading is halted | [Reconciliation runbook](../runbooks/reconciliation-mismatch.md) |
| `Not sent (stop cancellation not confirmed)` | IBKR did not confirm a stop's cancellation within a minute; the sale was not sent and the stop stays | Nothing: the next decision tries again. If it repeats, look at the stop in Client Portal |
| `Lost while sending, never resent` | The connection dropped while an order was sent and IBKR does not list it | Nothing: Tyche never resends ([ADR-0042](../adr/0042-ibkr-paper-adapter-at-most-once-orders.md)); the next decision starts from what the account holds |
| `the paper run failed: …` | Anything else. No state was saved for the half that failed; a *A run failed* alert was sent | Read the log (`logs/<date>.jsonl`), fix the cause, run again |

# Runbook: reconciliation mismatch

**Use it when** Discord says *Reconciliation mismatch: trading is halted*, or `tyche kill` or `tyche resume` shows `halted by reconciliation`. Tyche compared its own records with IBKR's, found a difference it will not guess about, and stopped trading ([ADR-0044](../adr/0044-reconciliation-exact-positions-broker-cash.md)).

What the halt does:

- **From the next decision on, Tyche sends nothing.** Every holding is kept; protective stops already at IBKR stay and can still sell.
- **A kill-switch flatten waits.** Tyche's holdings are what is in doubt, so it will not size sales on them. If you need out now, sell in IBKR's own app (step 4).
- **It stays until you run `tyche resume`.** A later run that finds the records agree again does not lift it: you look first.

What does **not** halt, and needs nothing from you:

- **Cash within the tolerance.** IBKR charges fees and pays interest Tyche does not model, and holds a dividend as accrued until it pays it, perhaps net of withholding. A gap up to `cash_tolerance` (USD 1.00 in the template) plus the dividends on their way is taken from IBKR without a word.
- **An order IBKR no longer lists, with no shares moved.** IBKR cancels resting stops by itself (at the end of the quarter after the one they were placed in, after 90 days without a login, after some corporate actions). Tyche drops the order from its records, Discord says *Reconciliation: N order(s) ended at the broker*, and the next decision places the stop again.

> **Today** (Phase 2, PR 13) nothing runs a reconciliation yet: the paper cycle does, from PR 14. `tyche resume` already lifts the halt.

## Before you start

- Know which workspace is the real one. Use `--home <folder>` on every command below if `TYCHE_HOME` is not set to it.
- Do not run `tyche resume` while a paper run is running. Nothing stops you yet; the scheduler (PR 15) will.
- Have IBKR's own app open on the **paper** account: Client Portal (**Portfolio**, and **Trade** → **Orders & Trades**) or IBKR Mobile.

## Find out what differs

1. **Read the alert, or ask Tyche.**

   ```bash
   uv run tyche resume --reason "reading it"
   ```

   It shows the halt, with one line per difference, and what resuming would apply. **Answer `n`.** Nothing changes.

2. **Match each line to a cause.** Each line starts with its kind:

   | Kind | Means | Usual cause |
   |---|---|---|
   | `position` | IBKR holds a different number of shares than Tyche | An order filled on a day no run read (see *Explained*); a trade you made by hand in the account |
   | `unknown_order` | IBKR has one of Tyche's orders working that Tyche does not expect | A run that failed after sending it: its state was never saved |
   | `foreign_order` | The account has working orders that are not Tyche's | An order you placed by hand, in the account Tyche trades |
   | `order` | IBKR and Tyche disagree on how many shares an order has left | A partial fill on a day no run read |
   | `cash` | The cash gap is larger than the tolerance and dividends on their way | A fee or interest larger than the tolerance; a deposit or withdrawal; a currency conversion |
   | `unresolved` | The IBKR adapter could not settle something it read | An execution still waiting for IBKR's commission report; a corrected execution |

   An **Explained** line names one of Tyche's orders that IBKR no longer lists and that accounts exactly for a position difference: it filled on a day no run read. Its price is inferred from the cash that moved, commission included. `tyche resume` applies it.

## Fix it

3. **If every difference is explained**, check one thing in IBKR's app: the order's fill (**Trade** → **Orders & Trades**, the trade history) matches the instrument, side and shares. The price will differ slightly from the inferred one by the commission. Then go to step 5.

4. **If anything is not explained, make the account match Tyche's records by hand,** or decide to start again from cash:

   - **An `unknown_order`:** cancel it in Client Portal (**Trade** → **Orders & Trades**, the order's **pencil icon**, **Cancel Order**). Do **not** use **Cancel Orders** in IBKR Mobile's menu: it cancels every working order, Tyche's stops included. If it already filled, its shares show as a `position` difference: sell them by hand.
   - **A `foreign_order` or a `position` from your own trade:** undo it in IBKR's app. Tyche trades this account alone.
   - **A `cash` difference you understand** (a deposit, a fee): resuming takes IBKR's cash as the check recorded it.
   - **An `unresolved` line:** wait a few minutes for IBKR's commission report; the next run reads it again.
   - **Anything you cannot explain:** leave the halt on and look at the journal and the logs (`logs/<date>.jsonl`). Stopping is the safe state.

## Start trading again

5. **Resume.**

   ```bash
   uv run tyche resume --reason "what you checked"
   ```

   It lists what it will apply: each explained fill, IBKR's cash as recorded, and orders that ended. If a later check already agreed with IBKR (you fixed the account by hand), it says *resuming applies nothing*. Answer `y`.

6. **Expected result:** `Lifted the reconciliation halt`, an `Applied:` line per explained fill, `Recorded as run resume-<time> in the state database`. With a webhook set, the channel gets *Trading resumed*.

7. **Confirm at the next run.** It reconciles again before deciding. A match (or *ended* orders only) means trading carries on. **A difference still there halts again**: go back to step 1.

## If it did not work

| You see | Do |
|---|---|
| `the reconciliation halt cannot be applied to the latest checkpoint` | The halt names an order the last state does not hold: a bug. Nothing was written and trading stays stopped. Keep the workspace as it is and report it with the log. |
| `the state database cannot be read, so a halt cannot be ruled out` | Fix the database first ([state database](../developer-guide/state-database.md)). |
| `changed since you confirmed` | A run saved new state while you were reading. Run `tyche resume` again and read what it shows. |
| `check this machine's clock` | The last saved state is newer than this computer's clock. Fix the clock; nothing was written. |
| The same mismatch after every resume | The account still differs. Step 4 did not fix it, or something trades the account besides Tyche. |

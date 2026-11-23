# Runbook: the kill switch

**Use it when** you want Tyche to stop placing new orders now: the market looks wrong, Tyche looks wrong, or you want time to think. It is also how you start again: after the kill switch, or after the **drawdown kill** halted trading by itself ([ADR-0035](../adr/0035-account-rules-and-the-drawdown-halt.md)).

What it does ([ADR-0039](../adr/0039-kill-switch-and-manual-restart.md)):

- **From the next decision on, Tyche buys nothing.** Decisions run after each session's close, so the switch takes effect at the next cycle, not at once.
- **Without flatten,** every holding is kept and its protective stop stays at the broker, still able to sell.
- **With flatten,** the next cycle cancels every stop, then sells every holding at the next open with market orders.
- **Orders already at the broker are not cancelled.** Market orders sent by the last run, for the next open, still fill. `tyche kill` lists them, and step 3 below is how you cancel one.

> **Today** (Phase 2, PR 8) nothing trades yet: the paper cycle arrives in PR 14. The commands work, and the paper cycle will read the switch at every decision.

## Before you start

- Know which workspace is the real one. Use `--home <folder>` on every command below if `TYCHE_HOME` is not set to it.
- Do not run `tyche kill` or `tyche resume` while a paper run is running. Nothing stops you yet; the scheduler (PR 15) will.

## Stop trading

1. **Engage the switch.**

   ```bash
   uv run tyche kill --reason "what you saw"
   ```

   Add `--flatten` to sell everything at the next open; it asks you to confirm. You should see `Kill switch engaged`, your reason, what happens to holdings, and then either the orders the last run left working at the broker or `left no order working`.

   *If the command itself fails*, create the file by hand: `touch "$TYCHE_HOME/KILL"`. An empty `KILL` file engages the switch without flatten.

2. **Read the list of working orders.** Each line is an order id, side, quantity, instrument, order type (and stop price), and time in force. Stops are your protection: leave them unless you mean to remove it. Market orders fill at the next open unless you cancel them.

3. **If you want a working market order gone, cancel it in IBKR's own app.** Find it by the order id, or by instrument, side and quantity, and cancel it there. *The exact steps in IBKR's apps are written in Phase 2, PR 10, once checked on the paper account.* Tyche never cancels for you: only the decision cycle talks to the broker.

4. **Confirm.** `cat "$TYCHE_HOME/KILL"` shows `reason`, `flatten` and `engaged_at`. Running `uv run tyche kill` again changes nothing and says `was already engaged`. A switch that flattens is never turned back into one that does not; only resuming releases it.

**After the next cycle**, its plan shows `killed` on every holding (or `flattened`, with sale orders and the stop cancellations before them).

## Start trading again

1. **Ask Tyche what it would lift.**

   ```bash
   uv run tyche resume --reason "why it is safe now"
   ```

   It shows the kill switch, if engaged, and the drawdown halt, if the last run's state carries one, with when and why. **Lifting a halt forgets the peak:** the next close becomes the new peak, and the drawdown kill counts from there. Answer `y` only if you mean it.

2. **Expected result:** `Lifted the kill switch` (and/or `the drawdown halt`), then `Recorded as run resume-<time> in the state database` once paper has run, and `The next decision trades normally`. The `KILL` file is gone.

3. **Confirm.** `uv run tyche resume --reason check` now says `Nothing to resume`. If you resumed after a flatten, the next decision rebuilds positions from cash, with the usual risk limits.

## If it did not work

| You see | Do |
|---|---|
| `no workspace at …` | Wrong folder. Give `--home` with the real workspace, the one with `config/tyche.toml`. |
| `Could not read state/tyche.db` after `tyche kill` | The switch is still engaged: the flag is written first. Working orders are unknown, so check them in IBKR's app. |
| `the state database cannot be read, so a drawdown halt cannot be ruled out` | `tyche resume` refused, and trading stays stopped. Fix the database first ([state database](../developer-guide/state-database.md)). Deleting `KILL` by hand would release only the kill switch, not a halt. |
| `changed since you confirmed` | Something changed the switch or the state while you were reading. Run `tyche resume` again and read what it shows. |
| `check this machine's clock` | The last saved state is newer than this computer's clock. Fix the clock; nothing was written. |
| The `KILL` file reads as `engaged without flatten` with a reason saying it is unreadable | The file was edited by hand and is not valid. That is safe: no new orders, nothing sold. Run `tyche kill` (with `--flatten` if you meant it) to rewrite it. |

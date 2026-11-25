# ADR-0045: The paper cycle

- **Status:** Accepted (Pablo, 2026-11-24)
- **Date:** 2026-11-24

## Context

Phase 2, PR 14 is the milestone: one decision cycle on the paper account, end to end. Every part exists and is tested on its own. The engine and the stages are the backtest's ([ADR-0005](0005-backtest-paper-live-parity.md)); `IBKRBroker` sends at most once and reads IBKR through `sync` ([ADR-0042](0042-ibkr-paper-adapter-at-most-once-orders.md)); `DailyFeed` publishes each session since the last run and skips a decision that is too late ([ADR-0043](0043-daily-feed-and-the-catch-up-rule.md)); reconciliation compares a checkpoint with the broker's record and stores a halt ([ADR-0044](0044-reconciliation-exact-positions-broker-cash.md)); a checkpoint is saved at the end of every run ([ADR-0038](0038-checkpoints-across-restarts.md)); the kill switch is a flag file the gate reads ([ADR-0039](0039-kill-switch-and-manual-restart.md)); alerts are collected and sent after a run ([ADR-0040](0040-logs-secrets-and-alerts.md)). PR 14 wires them in order and decides what none of them could decide alone.

Earlier PRs left these questions here:

- **The first run has no checkpoint** to reconcile against (ADR-0044).
- **A market order still working at the next decision** halts the run as a bug today (`ExecutionError`). In the simulator it cannot happen. At IBKR a market-on-open order should end at the open, filled or cancelled, but whether paper even fills market-on-open orders is still paper check 2 ([facts page](../developer-guide/ibkr-orders-and-paper-account.md#10-to-confirm-on-the-paper-account)). Halting as a bug fails the run, which saves no checkpoint, so every later run fails the same way.
- **A sale behind a resting stop.** Execution cancels a sleeve's stop and sells its shares in the same decision (an exit, or a kill-switch flatten). The simulator cancels at once. `IBKRBroker` publishes `CANCELLED` only once IBKR confirms it, and sends an order the moment it is published. If the stop is still working when the sale fills, both could sell the same shares (ADR-0039 carried this here).
- **`sync` between drains**, and what to do with everything its report lists: lost orders, unaccounted orders, executions awaiting a commission, corrections (ADR-0042).

**Decided with Pablo on 2026-11-24, before any code:**

1. **One PR**, one command, not 14a and 14b.
2. **The first run** adopts the broker's cash and refuses any position or working order.
3. **A market order still working at the next decision** is a reconciliation halt, not a failed run.
4. **A sale behind a resting stop** waits for IBKR to confirm the cancellation.

The rest of the Decision (the cycle's order, what `sync` reports, how a run is recorded) was accepted with the ADR. Building it changed four details, each marked below and listed in PR 14 for Pablo's review: the cycle is recorded as two runs (decision 2); a stale order is judged at the session's close, not its open, and the approval accepts a halt dated after its close (decision 4); every new sell order is held, not only a sale (decision 5); the adapter forgets orders reconciliation dropped (decision 2, step 4).

## Decision

1. **One PR, one command** (Pablo, 2026-11-24). `tyche paper run` reads the broker, reconciles, decides, sends, reconciles again and saves a checkpoint. A run with no new final session (a second run the same evening) decides nothing and is still a full check of the account.

2. **One cycle, recorded as two runs.** Each step is in `tyche.runtime.paper`; the core gains no paper-only code. The stages are built twice, because the gate must be built from the checkpoint the startup reconciliation corrected (ADR-0044), and the stages must already exist when IBKR's fills are read. Each half is a run of its own in the state database, with its journal and its checkpoint.

   **The check, `paper-<time>-check`.**

   1. Load the config (`--risk-profile`, as every backtest command; default `default`), the secrets, and the latest checkpoint (decision 3 when there is none). Subscribe the stored journal first (ADR-0037), then `AlertCollector`, the account, the sleeve book and execution from the checkpoint, and `IBKRBroker`.
   2. Connect. The adapter refuses any account but `IBKR_ACCOUNT_ID`.
   3. **Read IBKR**: `sync`, between drains. New fills reach the account, the sleeves and execution as in a backtest; execution places the protective stop of each entry that filled ([ADR-0023](0023-execution-sleeves-stops-and-cash.md)), sent as decision 5 says.
   4. **Reconcile**: checkpoint the stages, `reconcile` against `record()`, journal the `ReconciliationEvent`, `correct`, and close the adapter's records of orders reconciliation dropped (`IBKRBroker.forget`), so they are not reported again. Save the checkpoint.
   5. **Report a standing halt**: a drawdown halt or a reconciliation halt from an earlier run is alerted (`stopped`), unless this check is itself a mismatch, already alerted. The kill switch is alerted at the decision, as before (ADR-0039). A halt does not stop the cycle: the gate reads it, so bars and closes are still taken in (ADR-0043).

   Saving here first keeps what was read: IB Gateway reports only today's executions, so fills read and then lost to a failed decision could not be read again.

   **The decision, `paper-<time>`**, only when a session has closed since the last decision (the session after the checkpoint's last close; the latest final session on a first run).

   6. Build every stage as the backtest runner does, from the check's checkpoint, with `IBKRBroker`, `SystemClock`, the guardrails' money caps (ADR-0034), `FlagFileKillSwitch`, and the gate's `unreconciled` from that checkpoint.
   7. Fetch the candidates and the benchmark through the cache, build a `DailyFeed`, warm the universe and the signals up through `DailyFeed.starts_at`, and run the engine over it. Every `CycleSkippedEvent` of the run is alerted, all in one alert.
   8. **Wait for cancellations** (decision 5), then `sync` once more.
   9. **Reconcile** as in step 4, and save the checkpoint.

   Then disconnect and send the alerts. A run that fails at any step saves no checkpoint for that half, disconnects, logs, and sends `run_failed_alert` (ADR-0038, ADR-0040).

3. **The first run starts from the broker's cash** (Pablo, 2026-11-24). With no checkpoint, Tyche's account starts from IBKR's settled cash and settlement schedule in the profile's cash currencies, with an empty sleeve book and no working orders. If IBKR holds any position, or any working order, in the account, the first run refuses to start and says what it found: Tyche cannot know which sleeve a position belongs to, nor what stop protects it. The first run reconciles nothing at startup, then decides on the latest final session, as any run does.

4. **A market order still working at the next decision is a reconciliation halt** (Pablo, 2026-11-24). Reconciliation gains one difference, `stale_order`: a Tyche market order that the broker still lists as working after the close of the session it was sent for, the first session to open after the order was created. The close, not the open, so a run during the day never halts on a fill IBKR has not reported yet. Execution's own check stays, as a bug check, but is skipped under a reconciliation halt, whose approval sends nothing. `ApprovedPortfolioEvent` no longer requires the halt to be dated before its `as_of`: the startup check always runs after the close it then decides on. The alert names the order; Pablo cancels it in IBKR's app, runs `tyche resume`, and the next run finds it gone with no shares moved and drops it (ADR-0044, rule 3).

5. **A sale waits for its stop's cancellation** (Pablo, 2026-11-24). A decision publishes a sale *before* it cancels the stop on the same shares, so the adapter cannot judge a sale when it sees it. `IBKRBroker` therefore holds **every new sell order**, market or stop, when it is published; after the drain, `release` sends each one whose instrument has no cancellation still waiting for IBKR's confirmation. A replacement stop waits too, so the old and the new stop never rest together. The paper cycle calls `sync` and `release` a second apart until nothing is held, for at most `CANCEL_WAIT` (60 seconds; a constant, not config). An order still held then is rejected, never sent, and alerted; the old stop stays, and the next decision tries again. Purchases are sent at once: a purchase never competes with a stop for shares.

6. **What `sync` reports.** Lost orders are already rejected by the adapter; they are alerted. Unaccounted orders, executions awaiting a commission and corrections reach reconciliation through `record()` and halt there. Executions that are not Tyche's are alerted and counted; reconciliation already halts on working orders that are not Tyche's.

7. **Every paper run is recorded** with a run id, `RunMode.PAPER`, the code version and the config hash, in the state database's journal and checkpoint. No `reports/` folder: the daily summary (PR 16) is the report.

## Alternatives considered

- **Two PRs**: 14a, a `tyche paper check` that reads the broker and decides nothing, then 14b, deciding. Smaller to review, and 14a could run against the paper account before any order was decided. Pablo chose one PR (2026-11-24).
- **Adopting positions on a first run.** Tyche would have to assign them to a sleeve and guess their stops. An account Tyche did not build is Pablo's to empty first.
- **Cancelling a stale market order automatically.** It would keep trading, but the order is a symptom of something Tyche does not understand (an IBKR behaviour not yet seen on paper); a halt shows it to Pablo first.
- **Keeping the stale-order bug halt.** It fails every run until someone cancels the order, saves no checkpoint, and so never records what it saw.
- **Sending the sale and trusting the cancellation.** An order sent after the close does not trade until the open, hours later, so the cancellation almost always lands first. Almost is not enough in a cash account, where two sales of the same shares are a short sale the account cannot make.
- **Holding the sale until the next run.** Safe, but every exit would trade a day late.

## Consequences

- `tyche paper run` joins the CLI. It connects to IB Gateway and needs `.env`'s `IBKR_` keys; an agent never runs it with Pablo's real `.env`.
- `DifferenceKind.STALE_ORDER` is added; the event catalog's `ReconciliationEvent` row says so.
- `IBKRBroker` gains `held`, `release`, `reject_held`, `forget` and `last_report`.
- `AlertKind` gains `cycle_skipped`, `orders` and `stopped`; `AlertCollector` collects `CycleSkippedEvent`s.
- Each cycle is two runs in the state database, so the journal has two run ids per evening with a decision.
- The first `tyche paper run` needs the paper account holding USD and nothing else. How USD reaches it is still an open decision in `STATUS.md`.
- Paper checks 2 (a market-on-open fill), 3, 4, 5, 7, 10 and 11 can only be run with this cycle; their results may change decisions 4 and 5.

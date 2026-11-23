# ADR-0039: The kill switch and the manual restart

- **Status:** Proposed
- **Date:** 2026-11-23

## Context

The brief asks for a **kill switch**: "a file flag plus a CLI command … When on, no new orders go out and everything is optionally flattened." It also says the drawdown kill "halts everything; only a manual restart resumes". [ADR-0035](0035-account-rules-and-the-drawdown-halt.md) built the halt as a latch in the risk gate, and [ADR-0038](0038-checkpoints-across-restarts.md) made it survive a restart. Neither said how a person turns trading off by hand, or back on.

Two constraints shape the answer:

- **Orders reach the broker only through `ApprovedPortfolioEvent`** (CLAUDE.md, never-do rule 2). So the kill switch cannot sell anything itself. It can only change what the risk gate approves.
- **Tyche runs once a day, after the close** (Phase 2, PR 14). Between runs nothing in Tyche is running. A switch engaged at night is seen by the next cycle, after the next close.

Pablo answered three questions on 2026-11-23, before any code:

1. **A flatten and the resting stops.** The flatten cancels each protective stop, then sends the market sale for the next open. If both stayed, a gap down at the open could fill the stop and the sale, selling shares the account does not hold. No session runs between the cancel after the close and the sale at the open, so nothing is unprotected meanwhile.
2. **An order already working at the broker** when the switch is engaged (a market order for the next open, sent by the last run). It is **left to fill or expire**, and `tyche kill` lists it. Cancelling it is Pablo's choice, in IBKR's own app. The CLI never reaches the broker. A cancel from Tyche can come later, with the Discord bot.
3. **The peak after a manual restart.** `tyche resume` **forgets the peak**: the first close after it becomes the new peak, and the drawdown kill counts from there. Keeping the old peak would halt again at the next close, since the account is still at least the limit below it.

## Decision

**The switch is a file.** `KILL` at the workspace root (`Workspace.kill_file`, already in the template's `.gitignore`). Its presence engages the switch. Its content says why, when and whether to flatten:

```toml
engaged_at = 2026-11-23T21:04:00Z
reason = "market chaos, stopping until I have looked"
flatten = false
```

`touch KILL` engages it without flatten, so the switch works even when the command does not. A file that cannot be read, or holds anything unexpected, engages it **without** flatten: a flag nobody can read must stop new orders, and must never sell everything. The `KillSwitch` port (`read() -> Kill | None`) is how the core sees it. `FlagFileKillSwitch` reads the file every time it is asked.

**The gate reads it at every decision.** `RiskGate(..., kill_switch=)` reads the switch when each `TargetPortfolioEvent` arrives, so a switch engaged while a run is going counts from its next decision. While the switch is engaged, the gate approves nothing (no targets, no adjustments) and attaches the `Kill` to the `ApprovedPortfolioEvent` (`kill`), as it attaches the drawdown halt. No `RiskEvent` is published for it: the approval is the record. Backtest commands pass no switch: the workspace's `KILL` file stops trading, not research. Tests pass a scripted one.

**Execution reads the approval:**

- **Without flatten**, as under the halt: every holding is kept (plan note `killed`), no order of any kind is sent, and stops already resting stay at the broker.
- **With flatten**, `wanted` is zero for every sleeve and every instrument, whether or not the sleeve decided, whether or not it is still listed, and even under the halt. Execution plans every holding to zero (plan note `flattened`), **publishes every stop's cancellation first**, then one market sale per instrument. It buys nothing. Each later cycle sells whatever is still held, until the switch is released.

**`tyche kill [--reason] [--flatten] [--yes]`** writes the flag (atomically, through a temporary file), with the wall-clock time. It refuses a folder that is not a workspace, because a `KILL` file in the wrong place protects nothing. A flatten asks for confirmation unless `--yes`. A switch already engaged is never weakened: asking again without flatten leaves a flattening switch as it is, and asking with flatten upgrades one that did not flatten. The flag is written before the state database is read, so a broken database cannot delay it. It then prints the orders the latest checkpoint left working and any drawdown halt it carries.

**`tyche resume --reason [--yes]`** is the manual restart, for both things that stop trading. It shows what it would lift and asks first. Then:

1. If the state database exists, it records the restart as **a run of its own**, `resume-<time>`: one `ResumeEvent` in the journal (the reason, the switch released, the halt lifted, the run whose checkpoint held it). If the latest checkpoint carries a halt, the same run saves a new checkpoint: the latest one's state with `AccountRulesState.resumed()` (no halt, no peak; the previous close stays, so the daily loss limit still compares with it). The checkpoint chain stays the one record of state ([ADR-0038](0038-checkpoints-across-restarts.md)). Nothing is edited, and every lift is in the journal.
2. Last, it removes the `KILL` file. If anything before fails, the flag stays and trading stays stopped.

It refuses when nothing is stopped, when the state database cannot be read (a halt cannot be ruled out), when the switch or the latest checkpoint changed since Pablo confirmed, and when the latest checkpoint is not older than the machine's clock. These are all checked before anything is written, so a journaled resume always took effect.

**Not yet.** Neither command checks that no paper run is running. The scheduler (PR 15) runs the cycle and will need a lock. Until then, the runbook says not to run them during a cycle. The paper cycle (PR 14) builds the gate with `FlagFileKillSwitch`, and reports a switch or a halt at startup.

## Alternatives considered

- **Flatten from the command, at once.** It would sell during the session rather than at the next open. But it would be a second path to the broker, and a market order sent in the middle of a session by a script is not how Tyche trades (end of day, ADR-0015). Rejected by rule 2.
- **Keep the stops during a flatten.** It risks a stop and a sale both filling at a gapped open, which is a short sale in a cash account. Rejected by Pablo.
- **Cancel working orders from `tyche kill`** (purchases only, or all). It needs a broker connection from the CLI, which is a cancel-only exception to rule 2. Rejected by Pablo for now. The Discord bot phase can revisit it with confirmation.
- **Keep the old peak on resume, or refuse to resume until recovered.** Either way a drawdown halt could only be lifted once the account had recovered while holding. Rejected by Pablo.
- **A `HaltEvent` for the switch and the halt** (as the event catalog planned). Execution would then have two inputs to combine, and the approval would no longer be the whole truth about what may be traded. Carrying both on `ApprovedPortfolioEvent` keeps the gate's approval as that truth (ADR-0035's reasoning). Whether reconciliation (PR 13) needs a `HaltEvent` is left to PR 13.
- **Keep the switch in the state database.** It would be auditable, but it needs a working database and Tyche to engage. A file can be made with `touch`, from a phone over SSH, or by a future Discord bot, and works when everything else does not.
- **Lift a halt by editing the latest checkpoint, or with a separate table.** Checkpoints are append-only. A separate table would leave two records that a restart must merge. A resume run with its own checkpoint keeps one chain, explained by the journal.

## Consequences

- **Turning trading off is one file.** Turning it on is one command, which leaves a record and a new checkpoint.
- **A flatten takes effect at the next open after the next cycle.** Engaged at 22:00 on Monday, it sells at Wednesday's open after Tuesday's cycle, at the earliest. A Monday-night order for Tuesday's open still fills. `tyche kill` says so, and the runbook shows how to cancel it in IBKR.
- **A flatten under the guardrails is never cut:** sales are never cut (ADR-0034), and long only is still checked after the cancellations.
- **Each resume gives the drawdown kill a fresh budget.** A run of resumes after losses could walk the account far below its first peak. That is Pablo's decision each time, and every one is in the journal with its reason.
- **Paper and live must confirm each cancel before the sale** (PR 11, PR 14): a real broker processes a cancel asynchronously. The simulator processes it at once.
- `ApprovedPortfolioEvent` gains a defaulted field (`kill`), `ResumeEvent` is new, and `PlanNote` gains `killed` and `flattened`. All are additions the codec reads with its current format ([ADR-0037](0037-state-database-migrations-and-stored-journal.md)).

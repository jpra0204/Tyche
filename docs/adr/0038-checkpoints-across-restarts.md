# ADR-0038: State across restarts: a checkpoint at the end of every run

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-23

## Context

A paper run is one decision cycle a day (Phase 2, PR 14): Tyche starts after the close, decides, sends orders for the next open, and stops. Until now every run began with cash only and an empty memory. To trade the same account day after day, each run must carry on from where the last one stopped.

Most of the pipeline's memory is already rebuilt at every start. The universe and the signals windows are warmed up from cached history ([ADR-0021](0021-strategies-see-a-window-handed-in.md), [ADR-0024](0024-backtest-runner-holdout-and-run-record.md)), and strategies, screening and the portfolio stage keep nothing between cycles. What is left cannot be rebuilt from the market, because it is the record of what Tyche did:

| Part | Kept by | Why it matters |
|---|---|---|
| Tyche's view of the account | `AccountState` | The second record reconciliation compares with the broker's (PR 13) |
| The sleeve book: each sleeve's shares, cost, entry date and resting stop | `SleeveBook` | Strategies see their own positions; the sleeves must add up to the account ([ADR-0022](0022-portfolio-targets-as-weights-in-sleeves.md)) |
| Working orders, with the shares each still owes each sleeve; the stop each sleeve wants once a purchase fills; the last decision handled | `ExecutionStage` | Orders sent after the close fill at the next open, after Tyche has stopped; their fills must be split between sleeves and their stops placed ([ADR-0023](0023-execution-sleeves-stops-and-cash.md)) |
| The previous close, the peak and the drawdown halt | `AccountRules` | The daily loss limit compares with yesterday's close; the drawdown kill with the highest close ever; a halt must survive a restart ([ADR-0035](0035-account-rules-and-the-drawdown-halt.md)) |

ADR-0023 left one question open: **store the sleeve book, or rebuild it from fills?** Rebuilding from fills alone cannot work: a crossing moves shares between two sleeves with no fill and no order, and the stops a sleeve wants are in no fill either.

Pablo answered on 2026-11-23, before any code: **a checkpoint, saved at the end of every run**, rather than replaying the stored journal through the stages (event sourcing).

## Decision

**What a checkpoint is.** `Checkpoint` (in `tyche.core.domain`) holds the four parts above as value objects: `Account`, `SleeveState`, `ExecutionState` and `AccountRulesState`, with the run id, the moment it was taken (the run's clock at its end), the code version and the config hash. It checks on construction that its parts agree: the sleeves add up to the account's positions, and every resting stop in the book is a working stop order of that sleeve and instrument. A checkpoint that does not add up is refused, never loaded.

**Each stateful component exports and accepts its own part.** `SleeveBook(start)` and `.state()`; `AccountRules(profile, start)` and `.state()`, reached through `RiskGate(..., rules=)` and `.rules_state()`; `ExecutionStage(..., start=)` and `.state()`; `AccountState` already starts from any `Account`. Nothing in the core decides differently after a restart: a stage started from its state is the stage it was.

**When it is taken.** At the end of a run that completed, after the last decision, between sessions. A run that fails takes none: its state cannot be trusted, and the next run carries on from the last good checkpoint. What a failed run had already sent to the broker is found by reconciliation (PR 13) and by idempotent order ids (PR 11), not by the checkpoint.

**Where it is kept.** A second table in the state database ([ADR-0037](0037-state-database-migrations-and-stored-journal.md)), migration `0002_checkpoint.sql`: one row per run, numbered in the order saved, with the payload as tagged JSON written by the journal's codec and its format number. It is append-only (triggers refuse updates and deletes), so every run's hand-over is kept. A row's run must have its journal stored: a foreign key to the run's first envelope, so the journal can always explain the state a checkpoint hands on. A checkpoint must be later than the latest one. The `CheckpointStore` port (`save`, `latest`, `read`) and `SqliteCheckpointStore` are the only way in. The compatibility rule of ADR-0037 applies unchanged: a checkpoint's types are domain value objects, and changing one in any way but adding a defaulted field needs a new codec format.

**What a restart does.** Load the latest checkpoint; build the stages from it; warm up the universe and the signals from the cache through the usual path; run. The run's first close must come after the checkpoint's last close, or the account rules refuse it, so a session can never be measured twice.

**A halt survives a restart.** The drawdown halt is part of the checkpoint and comes back with it. Only the explicit manual restart of the kill switch (PR 8) lifts it.

**What is not saved.** The latest closes each stage has seen. The restarted run's first session supplies them; an instrument held without a bar that session fails closed with "no closing price seen", which the freshness rule (PR 12) will turn into a skipped, reported cycle.

**How it is proven.** A backtest can carry on from a checkpoint (`run_backtest(..., resume=Resume(checkpoint, broker_state))`), with the simulator carrying on from its own state (`SimBroker.state` and `SimBroker.resume`) as the real broker keeps the account while Tyche is stopped. Two years of three sleeves sharing four instruments, run straight through and run cut in two, must publish the same fills, closes, plans, approvals, orders and risk events, and end in the same state. Tested at cuts with market orders working, with stops resting in two sleeves, at month ends, just before and just after a drawdown halt, and through the SQLite store.

## Alternatives considered

- **Replay the stored journal through the stages (event sourcing).** No second copy of the state, and the journal is already complete. But today's code would re-interpret old events, so a fix to execution could quietly change the rebuilt past and therefore the present; the replay grows with every day traded; and it needs snapshots eventually anyway. Pablo chose against it. The journal stays the evidence for each checkpoint, and the two can be checked against each other later.
- **Rebuild the sleeve book from fills.** Cannot see crossings or wanted stops (above).
- **Relational tables per part** (positions, orders, sleeves). Queryable by hand, but four schemas to migrate for state that is always read and written whole, and a partial write could leave parts that disagree. One row per checkpoint is written in one transaction and checked as a whole.
- **Overwrite one "current state" row.** Smaller, but a bad save destroys the only good copy, and nothing would show what each run handed on. Rows are small; keeping them all is cheap.
- **Save after every decision cycle, or every event.** A paper run is one cycle, so the end of the run is the end of the cycle. Saving mid-cycle would capture states the checks above are not meant to hold.

## Consequences

- The paper cycle (PR 14) opens the database, loads `latest()`, builds the stages from it, runs, and saves the new checkpoint after its journal. The first paper run starts from cash, as a backtest does.
- A run that fails leaves the previous checkpoint as the latest. Restarting after a failure repeats the cycle from yesterday's state; reconciliation (PR 13) must then explain any order or fill the failed run left at the broker.
- Changing a stage's memory means changing its part of the checkpoint, and the restart tests fail first if a part is forgotten: a run cut in two must equal a run straight through.
- `BacktestResult` gains `checkpoint` and `broker_state`; backtests do not store them. `SimBrokerState` is not stored either: the real broker keeps its own record.
- A checkpoint is taken only between sessions; `SimBroker.state` refuses during one.

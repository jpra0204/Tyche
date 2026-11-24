# Catching up without acting on stale signals

**The pattern:** when a system that runs on a schedule has missed runs, separate *measuring* from *acting*. Catch up on every input you missed, in order, so that everything you measure (equity, drawdown, windows, counters) is as if nothing was missed. Then act only on an input that is still fresh, and judge freshness by **the deadline the action must meet**, not by the input's age.

## Why it matters here

Tyche decides once a day, after the close, and its orders execute at the next open. If the Mac was asleep for three days, three sessions went by without a run. Two wrong answers are tempting:

- **Skip the missed days.** Then the drawdown kill never sees the close at which the account fell 15%, and the daily loss limit compares with a stale close. The risk layer measures a world that did not happen.
- **Run every missed decision.** Then a signal computed on Monday's close is traded at Thursday's open, three sessions later than the decision assumed. That is a different trade from the one the strategy chose, and the backtest never made it.

The daily feed does neither. It publishes every missed session exactly as the backtest replay would (bars, closes, dividends, data problems), so every measurement is right. It runs a decision cycle only for a session whose decision can still reach the open it was made for. For each other session it publishes a `CycleSkippedEvent`, which the journal keeps and the paper run reports.

## A deadline, not an age

"Skip anything older than twelve hours" sounds like a freshness window, but it answers the wrong question. Friday's 16:00 close, caught up on Saturday morning, is eighteen hours old. Its orders would still go to Monday's open, exactly as on Friday evening. Monday's close caught up at 10:00 on Tuesday is also eighteen hours old, but Tuesday has already opened, and the order would trade on Wednesday.

What matters is whether the action can still happen at the moment it was meant for. So the rule names that moment: **a decision may trade until 30 minutes before the next session's open** (ADR-0043). The calendar supplies the next open, so weekends, holidays and early closes need no special cases. The 30 minutes leave room for the broker's own cut-off for market-on-open orders.

The deadline is checked when the cycle would start, not when the run began. A slow run that crosses 09:00 New York does not send.

## Re-using the replay

The daily feed does not rebuild the replay's logic. It *is* the replay, re-stamped with the wall clock: the same inputs in the same order with the same cycle ids, only the `DataReadyEvent` judged. Parity is then a property of the construction, not of two implementations kept in step, and the tests check it directly: a fresh session publishes exactly the replay's events.

The same idea explains the engine change. In a backtest the clock jumps to each input's moment. With the wall clock, an input is stamped when it became known, a moment that has just passed by the time it is handled, so it is published at once. Lookahead means publishing something *before* it was known. Publishing it a few milliseconds after is not lookahead.

## Waiting for data to settle

Data sources revise their latest values for a while: a closing auction prints, volume is corrected. A cache that never re-fetches turns an early, provisional value into permanent history. The defence here is cheap, because nothing is gained by hurrying: Tyche waits two hours after the close before it treats a session's bars as final, in every fetch path.

## In Tyche

- [ADR-0043](../adr/0043-daily-feed-and-the-catch-up-rule.md): the decision, and the two values Pablo chose.
- `src/tyche/core/feeds/daily.py`: `DailyFeed`.
- `src/tyche/core/domain/daily_cycle.py`: `DailyCycleRules` (`ready_at`, `trade_until`).
- `src/tyche/adapters/data/cached_provider.py`: `after_close`, the wait before a session is final.
- `src/tyche/core/pipeline/universe/stage.py`: a skipped cycle still counts as a session for a data problem's time out.
- `tests/core/feeds/test_daily.py`: parity with the replay, the weekend, the deadline, missing bars.

Related: [backtest, paper, live parity](backtest-paper-live-parity.md), [time as a port](time-as-a-port.md), [lookahead bias](lookahead-bias.md), [circuit breakers](circuit-breakers.md).

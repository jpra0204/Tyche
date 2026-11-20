# Strategies without memory

## What problem does this solve

A trading rule usually sounds like it needs memory: "rebalance once a month", "keep the stop where you set it at entry", "sell after the rebound". The obvious way to write it is a strategy object that remembers: a `last_rebalance` date, a `stop_price` field set on entry.

That memory is where backtest and live drift apart. A live process restarts (a crash, an update, a new day), and remembered state is lost, or saved and reloaded slightly wrong. A backtest that never restarts never sees the problem. The strategy then behaves one way in testing and another with money ([ADR-0005](../adr/0005-backtest-paper-live-parity.md)).

## The idea

Make the strategy a **pure function of what it is shown**: the same context always gives the same targets, and nothing survives between calls ([ADR-0021](../adr/0021-strategies-see-a-window-handed-in.md)). Then write each rule so that the fact it needs is already in the context:

- **"Once a month"** becomes "today's bar is in a different month from yesterday's". The window of bars says so; no date needs remembering.
- **"Keep the stop where you set it"** becomes "read the stop that is resting at the broker". The broker is the memory, and the strategy's `StrategyPosition` carries the stop back in at every decision. If the process restarts, the stop is still at the broker, and the next decision reads it back.
- **"Sell the rebound"** needs only today's close and the last five.
- **"Have I entered?"** is `context.position(instrument)`, which comes from the fills, not from anything the strategy wrote down.

This is the same principle as [state built from events](state-built-from-events.md), one level up: state lives where facts are recorded (the bars, the fills, the broker), and everything else is derived from them.

## Where is it in Tyche

- `src/tyche/strategies/trend_rotation.py`: `_first_session_of_month` compares the last two bars' months. Between rebalances, `_keep` reads the positions and asks for the same weight again.
- `src/tyche/strategies/mean_reversion.py`: at entry, the stop is computed and sent with the target. Later it is read back from `held.stop_price` and sent again unchanged. If no stop is resting, a new one is computed from that day's close.
- `src/tyche/strategies/indicators.py`: every indicator is a function of the window, so the same bars always give the same value.
- `tests/strategies/test_trend_rotation.py` and `test_mean_reversion.py` test each rule by building a context by hand: no engine, no clock, no history beyond the window.

## What does it cost

- **Some rules need rewording.** "Hold for ten days" must become "hold until the entry date in the position is ten sessions ago", using the entry date the position carries.
- **The window must be long enough for every derived fact.** The rotation needs two bars to see a month turn; an indicator with smoothing (Wilder's RSI) depends slightly on how many bars it is given, so the window length is part of the definition.
- **The broker becomes part of the strategy's state.** That is the right place for it in live trading, but it means paper and live must read stops back from the broker exactly as the simulator reports them: Phase 2's reconciliation checks this.

# ADR-0021: Strategies see a read-only window of history, handed in at every cycle

- **Status:** Accepted (Pablo, 2026-11-18)
- **Date:** 2026-11-18

## Context

A strategy needs past bars to decide anything: a moving average needs 200 closes, a breakout needs the last 20 highs. [ADR-0011](0011-pandas-at-the-edges.md) left open how a strategy gets them. The answer has to keep three promises the system already makes:

- **No lookahead.** A strategy must not be able to see a bar the clock has not reached ([lookahead bias](../learning/lookahead-bias.md)).
- **Parity.** The same strategy code must behave the same in backtest, paper and live ([ADR-0005](0005-backtest-paper-live-parity.md)).
- **Isolation.** A strategy is a plugin. It must not reach risk, execution, the engine or any port, which the import contracts already enforce, and adding one must need no core change (brief, section 5).

Three designs were on the table: hand each strategy a window at every cycle, let strategies subscribe to the bus and keep their own history, or let them query a data provider.

## Decision

1. **The window is handed in.** Each strategy declares a `timeframe` and a `lookback`, the number of bars it needs. The signals stage keeps the last bars of every instrument from the `BarEvent`s it has been sent, as many as the largest lookback for that timeframe. At every `ScreeningEvent` it calls `strategy.decide(context)` once per strategy.
2. **The context is everything a strategy may know**, and it is read-only:
   - `as_of`, the decision time;
   - `ranked`, the screening ranking, restricted to the instruments the strategy has a full window for;
   - `warming_up`, the ranked instruments it does not have a full window for yet, each with how many bars are held and how many are needed;
   - `history`, a view that returns exactly `lookback` bars for an instrument in `ranked`, oldest first, ending at `as_of`;
   - `positions`, the strategy's own current positions: instrument, quantity, entry date, entry price and current stop, if any.
3. **Strategies keep no state between cycles.** Everything they decide comes from the context. The positions view is what lets a stateless strategy tell an entry from a hold ("I already hold this, entered on 3 March at 412.10, stop at 395.00").
4. **Insufficient history is never silent.** An instrument with fewer bars than the strategy's lookback is not in `ranked` and has no window: asking the view for it raises an error. It is listed in `warming_up`, and that list is recorded in the strategy's `SignalEvent`, so the journal can say why it was not considered. A partial window is never handed out.
5. **Windows are keyed by instrument and timeframe.** The view's method takes both, `history.bars(instrument, timeframe)`. Phase 1 builds daily only, and the stage refuses a strategy of another timeframe, but intraday strategies will not need a different contract.
6. **A window holds one price basis, and is rebuilt rather than restated.** Prices are split-adjusted and dividends are cash ([ADR-0019](0019-split-adjusted-prices-and-cash-dividends.md)), so:
   - a dividend never changes a window;
   - a bar on a different adjustment basis from the rest of its window is refused: it is a bug upstream, and the run halts;
   - a window is never patched in place for a split. A new split makes the cache refetch the instrument's whole history (ADR-0019), and the windows are then rebuilt from the cache, through the warm-up path below. One way to fill a window, one arithmetic for splits: the cache's.
7. **There is one warm-up path, for every mode.** Before a run's first event, the windows are filled from the cache's `BarHistory` up to a given moment, keeping only bars at or before it. A backtest uses it to start with full windows on its first day (PR 15). Paper and live use it at the start of every run, and again after a split refetch (Phase 2). A restart therefore sees exactly what a backtest would have seen at that moment. The stage reports the history it needs (`timeframe` and largest `lookback`) so the runner knows how much to fetch.
8. **What a strategy's targets mean.** A strategy returns targets: instrument, weight within its budget (`Decimal`, between 0 and 1, all weights together at most 1), optional stop and a reason. An instrument the strategy could decide on (it is in `ranked`) and did not target has a target of zero. An instrument it holds but could not decide on this cycle (not ranked, or warming up) is not a decision to sell: portfolio construction keeps the position (PR 13). A data gap therefore never sells a holding by accident.
9. **A failing strategy does not halt the run.** If `decide` raises, or returns targets that break the rules above, the stage records the failure in `SignalsReadyEvent` and publishes no `SignalEvent` for that strategy. The other strategies are unaffected. A bug in the stage itself, or inputs that break its own assumptions, still halts the run (fail closed, ADR-0003).
10. **pandas stays outside the core.** The view returns Tyche's own `Bar` objects and tuples of floats. A helper in `tyche.strategies` will turn a view into a pandas frame when the first strategy wants one (PR 18). This settles item 4 of ADR-0011.

## Alternatives considered

- **Strategies subscribe to the bus and keep their own history.** The most freedom. But strategies become stateful and bus-aware: a paper or live restart has to rebuild each one's private state, a strategy could publish events, and one failing plugin halts the whole bus.
- **Strategies query a data provider.** The easiest to write. But lookahead would be prevented only by discipline, a live cycle would go to the network in the middle of a decision, and the strategy contract would need a port, which the import contracts forbid.
- **Hand out a partial window while an instrument warms up.** Simpler for the stage. But a 200-day average computed over 30 days is a different signal with the same name, and the strategy would have to remember to check.
- **Restate a window in place when a split takes effect.** Fewer refetches. But it is a second implementation of split arithmetic beside the cache's, and the two could disagree.

## Consequences

- A strategy is a pure function of its context, so it is tested by building a context, with no bus, clock or data.
- Memory is bounded: the largest lookback per instrument and timeframe.
- **Backtest windows are scaled by future splits.** The cache holds bars adjusted for every split known when they were fetched. In a backtest, before a split that happens later in the run, a window's prices are the traded prices divided by that future ratio; live saw the traded prices. Signals made of ratios (returns, moving-average crossovers, ranks) are identical. Signals that compare a price with a fixed number, and stop prices, are on the adjusted basis; that is consistent inside a backtest, because the simulated broker fills against the same bars. The universe's minimum price has the same limit (PR 11).
- **The positions view is a contract before it has a source.** Positions per strategy need two things that do not exist yet: which strategy a fill belongs to (portfolio construction, PR 13) and fills reaching Tyche's account view (execution, PR 14). Until then the view is always empty. Two strategies holding the same instrument each see their own share; how a fill is split between them is decided in PR 13.
- Strategy instances, their parameters and their budgets will come from `config/strategies/` in the workspace; loading them belongs with per-strategy budgets (PR 13). In PR 12 strategies are constructed in code.
- A strategy that needs more than one timeframe will need the stage to pass more than one window; the view's signature already allows it.

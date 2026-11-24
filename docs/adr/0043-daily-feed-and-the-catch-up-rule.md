# ADR-0043: The daily feed and the catch-up rule

- **Status:** Accepted (Pablo, 2026-11-24)
- **Date:** 2026-11-24

## Context

Paper and live run once a day, after the close ([ADR-0038](0038-checkpoints-across-restarts.md)). Until now only one `Feed` existed, `HistoricalReplay`, and only one paced clock, `SimClock`. Phase 2, PR 12 adds what a paper run needs to see the present: the wall clock in the engine, the session's bars fetched after the close through the read-through cache and published as the replay publishes them, and the brief's catch-up rule: *if the machine was asleep, fetch any missing data but never act on stale signals; anything older than a configurable freshness window is skipped and reported.*

Two values had no right answer in the code, and Pablo chose them on 2026-11-24, before any code:

- **How long after the close to wait.** Yahoo documents no time at which its daily bar becomes final. A bar fetched too soon may carry the last trade rather than the official closing auction price, or part of the day's volume. The cache's coverage rule then marks that session covered, and it is never fetched again ([ADR-0019](0019-split-adjusted-prices-and-cash-dividends.md), PR 5): a provisional bar would stay in every later backtest, not only one paper decision. Orders go to the next open as market-on-open orders ([ADR-0041](0041-orders-and-identity-at-ibkr.md)), so waiting costs nothing as long as the run ends before that open. **Chosen: two hours.**
- **When a decision is too stale to trade.** A decision at session D's close sends orders for D+1's open. Once D+1 has opened, an order sent now would trade at D+2's open on information two sessions old. A window measured as an age in hours goes wrong over a weekend: a run on Saturday after a missed Friday evening is still before Monday's open, and would send exactly what Friday evening would have. IBKR gives Nasdaq's MOO cut-off as 09:28 ET and none for NYSE Arca ([facts page, section 4](../developer-guide/ibkr-orders-and-paper-account.md)). **Chosen: a decision may trade until 30 minutes before the next session's open** (09:00 New York for a 09:30 open), across weekends and holidays.

## Decision

1. **Both values belong to the market profile**, in a new required table `[daily_cycle]` of `config/markets/<NAME>.toml`: `after_close_minutes = 120` and `before_next_open_minutes = 30`, whole minutes, never negative, covered by the config hash. `DailyCycleRules` in `tyche.core.domain` holds them; `MarketProfile.daily_cycle` carries it. Times come from the calendar, so an early close is waited on from its own close.
2. **The wait applies to every fetch.** `CachedDataProvider(..., after_close=)` treats a session as not yet closed until `after_close` has passed since its close: not asked for, not expected, never cached. `tyche data fetch`, paper and backtests all build the provider with the profile's value, so no path can cache a provisional bar.
3. **`DailyFeed` is the replay, re-stamped.** A new package, `tyche.core.feeds`, beside `tyche.core.backtest` in the core's layers. `DailyFeed` takes the candidates' histories (already fetched through the cache), the calendar, the clock, the rules and the first session the run has not seen. It publishes every session from that one through the latest final one, oldest first, by running `HistoricalReplay` over them: the same inputs, in the same order, with the same cycle ids. What changes is the stamp, the clock's reading as each input is published, and the bars' source name, `daily_feed`.
4. **Only the `DataReadyEvent` is judged.** When the feed reaches a session's `DataReadyEvent`, it reads the clock. Before `next open − before_next_open`, with a bar for every candidate, the event is published and the cycle runs. Otherwise a new `CycleSkippedEvent` is published in its place, with a `SkipReason`:
   - `STALE`: the deadline had passed. Every missed session but the last is stale by construction, since its next session has already traded.
   - `INCOMPLETE`: in time, but a candidate has no bar. Two hours after the close a missing bar is a data failure, and deciding without it could act on half a picture. A later run before the deadline can still trade it.
   Stale wins when both hold. Freshness is judged when the cycle would start, not when the run began, so a slow run that crosses 09:00 New York does not send.
5. **A skipped cycle still sees its session.** Its session events, bars, distributions and data problems are published as usual. Tyche's account view publishes its `AccountEvent`, the daily loss limit and the drawdown kill measure the close, and the signals windows take the bar. A drawdown reached during a missed session halts trading exactly as it would have. The universe counts a skipped cycle towards an instrument's time out after a data problem, as it counts a cycle that ran, so a catch-up leaves every stage as the cycles would have. Nothing else keeps memory between cycles (ADR-0038).
6. **The engine accepts a past moment from the wall clock.** An input is stamped when it became known, so with the wall clock that moment has just passed when the engine handles it. The engine's rule becomes: inputs in time order, none earlier than the run's start (`FeedOrderError` otherwise), then `wait_until` the input's moment. `PacedClock.wait_until` returns at once for a moment already passed on a real clock; `SimClock` still refuses to go back. `SystemClock` gains `wait_until`, sleeping until a future moment, and never reads earlier than a reading it already gave (an NTP step back).
7. **Exactly the candidate list.** `followed_instruments(profile)` is the candidates in their listed order, then the benchmark if it is not one of them: what a backtest reads and a paper run fetches ([ADR-0024](0024-backtest-runner-holdout-and-run-record.md)). `tyche data fetch --all` fetches that list; it refuses symbols, `--exchange` or `--asset-class` with it.
8. **One calendar per daily feed** for now. `CA+US` (Phase 4) needs two calendars' sessions merged, each with its own next open; the feed refuses a candidate on another calendar.

Not in this PR: nothing builds a `DailyFeed` yet. The paper run (PR 14) fetches through the cache, warms up through `DailyFeed.starts_at`, runs the engine over the feed, and reports `traded` and `skipped`. An alert for a skipped cycle comes with it.

## Alternatives considered

- **A freshness window as an age** (hours since the close). Simpler to state, but it skips a Saturday catch-up whose orders would equal Friday evening's, or trades a Friday close on Monday afternoon after the open, depending on the number. The deadline before the next open is what decides whether an order can still mean what the decision meant. Pablo chose against it.
- **Skip stale sessions entirely** (publish nothing for them). The account rules would miss their closes: a drawdown reached on a missed day would go unnoticed, and the daily loss limit would compare with a stale close. Publishing the session and skipping only the decision keeps every measurement honest.
- **Run the stale cycles with no orders**, as a halted backtest does. Strategies, the gate and execution would all run on days whose orders can never be sent, producing plans nobody can act on and journal entries that look like decisions. A skipped cycle says plainly what happened.
- **Decide without a missing candidate**, as a backtest does (the universe excludes it). In paper a missing bar two hours after the close is a failure of the data source, not a market fact; and a paper run sees only its own sessions' closes (ADR-0038), so a held instrument without its bar would stop the run anyway ("no closing price seen"), which ADR-0038 expected this rule to turn into a skipped, reported cycle. Skipping is the conservative reading, and the run before the deadline can be repeated by hand. The cost is a paper day skipped where a backtest would have traded; it is reported each time.
- **Re-fetch the latest sessions on every run** and compare, to catch a revised bar. Would catch revisions after the wait too, but needs the cache to forget coverage, and a revision would rewrite history a backtest already used. Waiting long enough is simpler; a revision after two hours is not handled.
- **Fetch inside the feed.** The feed could call the `DataProvider` itself. But the warm-up must read the same histories first, a fetch failure would surface inside the engine's loop instead of before the run, and the replay already takes histories. The run fetches, then builds the feed.

## Consequences

- A workspace created before PR 12 must copy `[daily_cycle]` from a new one; Tyche refuses to start without it. The config hash changes.
- `tyche data fetch` no longer asks for a session until two hours after its close. Run straight after the close, it fetches through the previous session.
- `CycleSkippedEvent` and `SkipReason` are new events in the catalog and the journal codec. The universe consumes `CycleSkippedEvent`.
- `FeedOrderError` now means "earlier than the input before it, or than the run's start"; a backtest replay is unaffected.
- The paper run (PR 14) must report every skipped cycle, warm up through `DailyFeed.starts_at`, and fetch exactly `followed_instruments`.
- A bar Yahoo revises more than two hours after the close stays as first cached.

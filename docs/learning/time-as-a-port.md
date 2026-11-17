# Time as a port

## The problem

Most code finds out the time by asking the operating system:

```python
if datetime.now() > market_close:
    run_end_of_day()
```

That one line quietly ties the code to the present moment. Three things break:

- **Backtests.** Replaying 2015, the code still believes it is today. Anything that compares a bar's time with "now" gives nonsense, and the error does not raise; it just produces a different result.
- **Tests.** A test of "skip signals older than the freshness window" passes or fails depending on when it runs. Testing a half day means waiting for a half day.
- **Markets.** "The close" is not one fixed time. New York closes at 16:00 local, which is 21:00 UTC in winter and 20:00 UTC in summer, and at 13:00 local on half days. Toronto has different holidays. Hard-coding any of it is wrong somewhere.

## The idea

Treat time like any other outside dependency: something the core asks a port for, never something it reaches out and grabs. Tyche has two ports for this.

- **`Clock`** answers one question: what time is it? It has a single method, `now()`, which returns a UTC datetime.
- **`Calendar`** answers questions about a market: is it open on this date, when does that session open and close, and is it a half day? The answers come back as `Session` objects with UTC times.

Then each mode plugs in the implementation it needs:

| | Backtest | Paper and live |
|---|---|---|
| `Clock` | `SimClock`: stands still until the engine moves it | The wall clock (Phase 2) |
| `Calendar` | The same in every mode: `ExchangeCalendarsCalendar` | |

`SimClock` is the interesting one. It does not tick. The engine moves it to each input's timestamp before publishing that input, so every event the input causes is stamped with the moment it would really have happened. It refuses to go backwards, because time running backwards can only mean the data feeding the engine is out of order.

A front-end comparison: testing a component that shows "5 minutes ago". You do not wait five minutes. You inject the current time, or use fake timers, so the test controls it. `SimClock` is fake timers for the whole trading system, and the backtest is the test.

## Where it is in Tyche

- Ports: `tyche.core.ports.clock` and `tyche.core.ports.calendar`.
- The session value object: `tyche.core.domain.session`.
- The simulated clock: `tyche.core.sim.clock`. It is pure code, so it lives in the core.
- The calendar adapter: `tyche.adapters.calendars`, backed by the `exchange_calendars` library.
- The event bus takes the clock's `now` method when it is created, so every envelope's `occurred_at` is simulated time in a backtest and real time live.
- The rule that keeps it honest: ruff's `DTZ` rules reject naive datetimes, and nothing in the core calls `datetime.now()`.

Two choices in the calendar worth knowing:

- **It refuses to guess.** A calendar is loaded for a range of dates. Asking about a date outside that range raises an error instead of answering "closed", because "is this a trading day?" has no safe default.
- **It rejects aliases.** `exchange_calendars` accepts `ARCX` or `NASDAQ` and quietly maps them to the New York calendar. Tyche's calendar refuses them and names the code to use, so the code that loads a calendar always says exactly which one it means.

## What it costs

- **Every component that needs the time has to be given a clock.** That is one more argument to pass around. The composition root does it once, in one place.
- **Projections are not facts.** A calendar's future sessions come from holiday rules. An unscheduled closure (a storm, a day of mourning) only appears after the library is updated, so the live scheduler must still handle a market that is unexpectedly shut.
- **A library dependency for the calendar.** Holiday rules are fiddly and change; writing them ourselves would be a source of bugs with no learning value. This is exactly what the brief means by using libraries at the edges.

The next step is lookahead bias: how the clock and the bar timestamps together make "could we have known this yet?" a question code can answer. That note arrives with the backtest runner.

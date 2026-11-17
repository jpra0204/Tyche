# ADR-0018: Market data is audited against the calendar, not trusted or rejected

- **Status:** Accepted (Pablo, 2026-11-17)
- **Date:** 2026-11-17

## Context

The brief says to treat the free data source as unreliable and to add retries, quality checks and gap detection. Free daily data has predictable faults: a session with no bar, a bar stamped at midnight instead of the close, the same day twice with different prices, a missed stock split that looks like a 50% crash.

There are two easy answers, and both are wrong for a system that trades money:

- **Trust it.** A missing day silently becomes a longer gap between bars, and a bad price becomes a signal.
- **Reject the whole series on any fault.** Twenty years of history are unusable because of one bad day in 2009.

## Decision

1. **Every answer is audited against the trading calendar.** The expected bars are exactly the sessions the calendar says the market was open, among those that have already closed by the `Clock`.
2. **Three outcomes, by how sure we can be:**
   - **Drop** a bar that cannot be right: not at a session close, another instrument's, the other adjustment basis, or conflicting with another bar for the same session.
   - **Keep and flag** a bar that is possible but doubtful: a close-to-close move beyond a threshold (50% by default).
   - **Report** a session with no bar. Nothing is invented to fill it.
3. **Every finding is returned with the bars.** `DataProvider.daily_bars` returns a `BarHistory`: the bars that passed and a list of `DataIssue`s. What to do about an issue (skip the instrument, stop the run, alert) is decided by the code that uses the data, not by the code that fetched it.
4. **Bars that are dropped are never cached.** The cache only ever holds bars that passed the audit.
5. **The audit is pure core code** (`tyche.core.domain.bar_history`), so the rules are the same whatever the source and are tested without any vendor.

## Alternatives considered

- **Fill gaps** by carrying the previous close forward. Common in backtesting libraries. It invents prices, hides the problem, and makes a stale price look like a quiet market.
- **Quality checks inside each vendor adapter.** Each source would implement its own rules, slightly differently.
- **Raise on any issue.** Simple and safe, but makes long histories from free sources unusable.

## Consequences

- Downstream stages must handle a `BarHistory` with issues. The universe stage (PR 11) will exclude instruments with recent gaps or unresolved suspect moves; the feed (PR 7) will publish each issue as a `DataQualityEvent` so the journal and Discord see it.
- The 50% threshold is a guess suited to large ETFs and stocks. It is a parameter, and may need a per-profile setting later.
- A suspect move that is real (a genuine crash) is still flagged every time. That is noise worth having.

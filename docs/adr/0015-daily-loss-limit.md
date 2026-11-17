# ADR-0015: The daily loss limit is measured close to close

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

The default risk profile has a daily loss limit: at −3%, no new entries for the rest of the day. That wording assumes a system watching the market during the session. In Phases 1 to 5 Tyche decides once per session, after the close, so the rule needed a precise meaning. Pablo confirmed the reading below in the Phase 0 review.

## Decision

1. **Measured close to close.** The day's loss is the change in total account equity from the previous session's close to this session's close.
2. **Everything that happened in the session counts:** price moves on open positions, positions closed by a stop, and all fees and commissions (and conversion costs once currency conversion exists). Deposits and withdrawals are not gains or losses and are excluded.
3. **Effect.** If the loss for session *t* reaches the profile's limit, the decision cycle at the close of *t* opens no new positions and does not add to existing ones. Exits and reductions still go through. The block lasts for that cycle only; the next session starts fresh.
4. **Every trigger is recorded** as a `RiskEvent` and reported in the Discord summary.
5. **With intraday data (Phase 6)** the same rule is evaluated at each intraday cycle against the previous close, which is when "for the rest of the day" takes its literal meaning.

**What this rule does not do.** It offers no protection *during* a session. In an end-of-day system, between two runs of Tyche the only thing that can act is an order already resting at the broker:

| Protection | Acts when | Covers |
|---|---|---|
| Stop order at the broker ([ADR-0006](0006-target-positions-with-optional-stops.md)) | During the session, with Tyche off | One position, only if its target carried a stop |
| Daily loss limit (this ADR) | At the decision after the close | Stops new risk being added after a bad day |
| Drawdown kill switch | Each time Tyche runs: at every cycle and at startup | The whole account, across days |

The drawdown kill switch is the backstop across sessions. Like the daily loss limit it is evaluated when Tyche runs, so in an end-of-day system it is not an intraday mechanism either. It becomes one when intraday cycles exist. A position without a stop has no protection inside a session; its loss is bounded only by its size.

## Alternatives considered

- **Open to close.** Ignores overnight gaps, which is where much of a daily loss comes from.
- **Realised losses only.** A portfolio could be deeply down on open positions and still be allowed new entries.
- **Poll the broker during the session to enforce it intraday.** That is intraday trading infrastructure, which the roadmap places in Phase 6.

## Consequences

- The rule is a simple comparison of two `AccountEvent` equity values, and behaves identically in backtest, paper and live.
- A backtest can count how often the limit triggered and what it cost or saved.
- The user guide page on risk profiles must state plainly what protects a position within a session and what does not.
- Strategies that hold positions without stops rely on position sizing for intraday risk. The strategy how-to will say so.

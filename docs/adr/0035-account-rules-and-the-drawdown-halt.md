# ADR-0035: The account rules: the daily loss limit in the gate, and a drawdown halt that a backtest runs through

- **Status:** Proposed
- **Date:** 2026-11-23

## Context

Every risk profile has two limits measured on the whole account rather than on a position ([ADR-0032](0032-risk-limits-in-three-layers.md)): a **daily loss limit** (`default`: 3%) and a **drawdown kill** (`default`: 15%). [ADR-0015](0015-daily-loss-limit.md) fixed what the daily loss limit means in an end-of-day system: close to close, every cost included, no new entries or additions at that close, and only that close. The brief says the drawdown kill "halts everything; only a manual restart resumes". Until now neither was applied. Phase 2, PR 4 applies both.

One question was Pablo's to answer, and he did on 2026-11-23, before any code: **what a backtest does after the drawdown kill**, since it cannot model a person deciding to restart. He chose to **run on to the last day with no orders**: what a paper or live account would do if nobody restarted it. The alternatives were to flatten and sit in cash (assumes he would always flatten, which the kill switch leaves optional) and to end the run at the halt (halted and unhalted runs would then cover different ranges and could not be compared).

## Decision

**The gate applies both rules.** They are risk rules, and the gate is where risk rules live. A pure `AccountRules` object holds the state and decides. `RiskGate` feeds it every `AccountEvent`, publishes what it finds and applies it.

**Both are measured at every session close**, from the `AccountEvent` published before that close's decision, whether or not a decision follows. Equity is the account's: cash, settled or not, plus positions at their latest close, after every fee. It is the whole account's equity, not the trading equity sized on under a capital cap ([ADR-0034](0034-order-level-guardrails.md)), because the rule is about what the account can lose. Each cash currency is measured on its own until currency conversion exists (Phase 4), as the money caps are. A rule triggers when the fall reaches its limit, equal included.

**The daily loss limit** compares this close with the previous one. When it triggers:

- an `AccountTrigger` (rule `daily_loss_limit`, the close, the previous equity, this equity, the limit, a reason) is published as a `RiskEvent`;
- the decision at that close, if any, has every contribution above what its sleeve holds brought down to the holding (rule `daily_loss_limit`, scope `account`). Nothing is entered, and nothing is added to, an instrument another sleeve holds included. Exits, reductions and holdings kept as they are go through. This applies first, before the position rules ([ADR-0033](0033-risk-gate-position-rules.md)), which can only lower what is left;
- the next close starts fresh.

**The drawdown kill** compares this close with the highest close so far. When it triggers, it is published as a `RiskEvent` like the daily loss, and trading halts. **The halt is a latch:** nothing in a run clears it, not even a new high. From then on the gate approves every proposal with no targets, no adjustments and the trigger attached (`ApprovedPortfolioEvent.halt`). That approval reads as "keep everything" for every sleeve and instrument. Execution then sends no order of any kind: no sale, no purchase, no stop placed again or cancelled. Its plan shows every holding with the note `halted`. Stops already resting at the broker stay there and can still sell, because they are protection already in place, not a new decision.

**A halted backtest runs on to its last day.** Positions are held and marked at each close, dividends are credited, resting stops can fire. The equity curve and every metric cover the whole range, so a halted run stays comparable with its benchmark and with other runs. The engine's own "halted" (a stage failing closed, [ADR-0003](0003-synchronous-event-bus.md)) is a different thing and keeps its meaning: the run stopped because of a bug.

**The record and the report say so.** `run.json` gains `outcome.account_rules`: how many closes triggered the daily loss limit, and the halt (its close, the peak, the equity, the drawdown and the limit) or `null`. `risk.applied` now lists both rules. The trigger events are not counted with the gate's cuts. The report adds a warning at the top when the run halted, saying what happened and that paper or live would resume only on a restart. It marks the halt on the equity and drawdown charts and gives both counts in "What ran". The command's summary has an `Account rules:` line.

**Lifting a halt** is a manual restart, which arrives with the kill switch (PR 8): the two share their state, and the halt is saved across restarts with the rest of the state (PR 7).

## Alternatives considered

- **Flatten at the next open, then hold cash.** It models one particular human reaction. The kill switch makes flattening optional, so the backtest would be assuming a choice Pablo has not made. Rejected by Pablo.
- **End the run at the halt.** Simplest, but the metrics would cover a shorter range than the benchmark's full one and than other runs'. A walk-forward fold or a sweep trial that halted would be measured over a different stretch. Rejected by Pablo.
- **Model a restart after some days.** Invents a rule for a person's decision, and a backtest that "recovers" by a made-up restart would flatter the strategy.
- **Apply the halt in execution rather than the gate.** Execution would then need to know about equity peaks, and the gate's approval would say "buy" while execution refused. Keeping it in the gate means `ApprovedPortfolioEvent` is still the whole truth about what may be traded.
- **Let a halted gate still allow exits.** "Halt everything" is the brief's rule, and a strategy that sells in a crash may sell at the bottom. A resting stop still protects each position that has one. Whether a halt should also flatten is the kill switch's decision (PR 8), not a silent default here.
- **Measure the drawdown on trading equity.** Under a capital cap, trading equity is the cap while the account is above it, so a fall would not show until the account dropped below the cap. The account's own equity is what the brief means.

## Consequences

- **Under a profile whose limits do not bind, nothing changes:** every existing result is reproduced exactly. The test profile `UNBOUND` now sets both limits to 99% so it stays that way.
- **A strategy that falls 15% under `default` stops trading for the rest of a backtest.** Its result then shows the cost, or the benefit, of not trading after a crash. That is honest about what the rule does. It also means a profile's drawdown kill is part of what a backtest tests, and comparing profiles side by side (PR 5) will show it.
- **Deposits and withdrawals would read as gains and losses.** Nothing in a backtest makes one after the start. Paper must exclude them when it reads the broker's cash (PR 13), as ADR-0015 requires.
- **Walk-forward, sweep and capital reports do not yet say which runs halted.** Each run's own record does. The side-by-side profile report (PR 5) is where a halt must show at a glance.
- **Before paper trading, the halt lives only in memory.** A restart today is a new run, which is the manual restart. PR 7 saves it, and PR 8 adds the command that lifts it.

# ADR-0034: Order-level guardrails: size on the capital cap, shrink purchases to the money caps, halt on a short or on leverage

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-23

## Context

The risk gate works in weights ([ADR-0033](0033-risk-gate-position-rules.md)). Orders are only sized in shares afterwards, in execution, from equity, the last close and the cash, so only execution can check the guardrails that are about money and shares: long only, no leverage, the most one order may be worth (`max_order_value`) and the most Tyche may trade with (`max_total_capital`) ([ADR-0032](0032-risk-limits-in-three-layers.md)). Phase 2, PR 3 adds that last check.

Pablo plans a live account that starts small and grows in steps, raising the caps by hand at each step. Three questions came up, and he answered each on 2026-11-23, before any code:

1. **Where do the money caps bind?** They describe the real account, so **in paper and live, not in research backtests**, which keep their own starting cash and apply only the percentage limits. `tyche capital` already shows what a smaller account does to a strategy ([ADR-0031](0031-minimum-viable-capital.md)).
2. **What does the capital cap limit when the account holds more than it** (a deposit, or gains)? Pablo chose: **size as if equity were the cap.** Every position is planned on the lower of the account's equity and the cap; money above the cap, gains included, stays in cash until he raises it. (The alternative sized on the whole account and cut purchases at the cap, which gives positions smaller than planned and uneven, and a cut at almost every decision.)
3. **A purchase over a cap: refuse it or shrink it?** Pablo chose: **shrink it** to the whole shares that fit, and refuse it only when not one share fits. Refusing would mean a position sized right at the cap, such as one whole-account position on a small account, never opens.

## Decision

**The caps apply when a run is given them.** `ExecutionStage` and `RiskGate` take an optional `money: Mapping[Currency, MoneyLimits]`, built from the guardrails (`Guardrails.money_limits()`). `BacktestSpec.money_limits` carries it to both; the backtest commands pass `None`, and the paper run (PR 14) will pass the workspace's caps. This is wiring in the composition root, not a mode check inside the core ([ADR-0005](0005-backtest-paper-live-parity.md)): a replay of a paper period (PR 19) passes the same caps paper had.

**With caps, execution sizes on the trading equity:** the lower of the account's equity and `max_total_capital`, per currency. The risk gate weighs holdings against the same figure, or the two would disagree about how large a position is. `ExecutionPlanEvent.sized_on` records the figure for every decision, caps or not.

**Then each purchase is fitted, in this order:**

1. **The order cap.** Each purchase is cut to the whole shares whose value is within `max_order_value`.
2. **The capital cap.** What stays invested after the cycle's sales (valued at the last close), plus the purchases, must be within `max_total_capital`. Above it, every purchase shrinks in proportion, then one share at a time from the largest, as for cash.
3. **Cash**, as before ([ADR-0023](0023-execution-sleeves-stops-and-cash.md)).

Purchases are valued at the last close plus the price buffer, the price cash is already fitted at, so an open up to the buffer above the close cannot take an order past a cap. A larger gap can, by the size of the gap: a market order's fill price cannot be bounded in advance. Sales are never cut; they only reduce risk.

**Every cut is recorded.** An `OrderAdjustment` (rule `max_order_value` or `max_total_capital`, scope `order`, action `shrink` or `block`, the instrument, the shares before and after, the cap and a reason) is published as a `RiskEvent`, with the active profile's name, before the `ExecutionPlanEvent`. Each sleeve whose share of the purchase was cut gets the plan note `capped`. The run record counts the cuts with the gate's, and says which caps applied (`risk.money_caps`, `null` for a research backtest).

**Long only and no leverage hold in every run, caps or not, and a breach halts.** Execution checks, after planning, that this cycle's sales and every stop left resting never add up to more shares of an instrument than the account holds, and that the purchases cost no more than the buying power. Execution is built so that neither can happen, so a breach is a bug, and the run stops ([ADR-0003](0003-synchronous-event-bus.md)'s fail-closed rule) rather than being trimmed and carrying on.

## Alternatives considered

- **Apply the money caps in research backtests too.** A backtest starting with USD 10,000 under a USD 690 cap would size as if it had 690: the same result as a backtest at 690 with the rest idle. `tyche capital` already runs at chosen sizes, and does it properly.
- **Size on the whole account, cut at the cap** (Pablo's decision 2).
- **Refuse an over-cap purchase** (Pablo's decision 3).
- **A separate risk stage between execution and the broker**, approving each order. Orders would then need a second approval event and execution a second subscriber; the check is a few lines inside the stage that already sizes the orders, and it publishes its cuts as `RiskEvent`s, so the journal sees them the same way.
- **Value purchases at the last close, without the buffer.** Simpler, but the buffer is what cash uses, and an open a little above the close would routinely take an order past its cap.

## Consequences

- **Nothing changes in a research backtest.** The money caps are not passed, and long only and no leverage already held. Every existing result is reproduced exactly.
- **The caps are only exercised by tests until paper trading exists** (PR 14). The unit tests, a property-based test (no purchase ever exceeds either cap, for any cash, caps, price or weight) and a runner test cover them.
- **At the first live stage the caps bind hard.** With a USD 690 cap, one share of SPY at about USD 690 plus the 2% buffer does not fit, so the purchase is blocked; cheaper funds are bought instead, a share or so smaller than planned.
- **Raising a cap is the way to put more money to work.** Gains above the cap sit in cash. That is the point: the cap is changed by hand, in the workspace's own history, never by the system.
- **The order check does not yet see the daily loss limit or the drawdown kill**; those are account rules in the gate (PR 4).

# ADR-0006: Target positions with optional stops; typed risk approval

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

The brief describes a trade in two different ways.

- Section 4.2 is **weight-based**: strategies output signals or target weights, portfolio construction merges them into a `TargetPortfolioEvent`, and execution trades the difference between target and current positions.
- Section 7.1 is **trade-based**: "risk per trade 1% of equity (the most one position can lose before its stop triggers)" assumes each position has an entry, a stop and a size derived from the distance between them.

An ETF rotation has no natural stop. A breakout strategy is defined by one. The core needs one contract that serves both. Separately, the pipeline runs once after the close, so nothing inside Tyche can protect a position during the session.

## Decision

1. **Target positions are the single contract.** Every strategy outputs target weights within its own budget. Execution always works by diffing targets against current positions.
2. **A target may carry an optional stop price.**
   - **With a stop:** the risk layer sizes the position so that being stopped out loses at most the profile's risk per trade: `quantity ≤ (risk_per_trade × equity) ÷ (reference_price − stop_price)`. After the entry fills, a stop order rests at the broker.
   - **Without a stop:** risk per trade does not apply. The position is still bound by max position size, max open positions, the daily loss limit, the drawdown kill switch and the guardrails.
3. **Stops rest at the broker.** A stop is a real order held by IBKR, so it works while Tyche is not running. In backtests `SimBroker` evaluates stops against each bar's high and low, and fills at the open if the bar gaps through the stop.
4. **Risk approval is a type.** Portfolio construction publishes a proposed `TargetPortfolioEvent`. The risk gate is the only component that can publish `ApprovedPortfolioEvent`, and execution subscribes to nothing else. Skipping risk is a wiring error that cannot be expressed, not a rule someone must remember.

## Alternatives considered

- **Every position must have a stop.** The simplest reading of section 7.1 and the most protective, but the buy-and-hold benchmark and weight-based strategies would need invented stops that distort them.
- **No broker stops in v1.** Simpler broker port and simulator. Rejected because nothing would protect a position intraday or while the machine is asleep.
- **Two contracts, one for weights and one for discrete trades.** Two code paths through portfolio construction, risk and execution, in the part of the system where bugs cost money.

## Consequences

- The `Broker` port needs stop orders from Phase 1, and `SimBroker` needs a rule for stops against daily bars. With only open, high, low and close we cannot know the order of events inside a day, so the rule will be the pessimistic one and will be documented.
- A stop makes a position smaller, never larger: sizing by risk can only reduce what the size cap already allows.
- Stop-outs happen between decision cycles. They arrive as fills with no cycle, and the next cycle must see the position as closed. Reconciliation covers the case where a stop fired while Tyche was off.
- Strategy authors must say whether each target has a stop. The strategy how-to will explain the trade-off.

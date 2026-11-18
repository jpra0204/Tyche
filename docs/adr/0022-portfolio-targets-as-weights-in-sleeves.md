# ADR-0022: Portfolio targets are weights of equity, held in one sleeve per strategy

- **Status:** Accepted (Pablo, 2026-11-18)
- **Date:** 2026-11-18

## Context

Portfolio construction (brief, section 4.2) combines the signals of several strategies running at once, gives each a configurable budget and resolves conflicts between them. Three questions had to be answered before it could be built:

1. **In what unit is the combined target?** The event catalog said share quantities. Quantities need the account's equity and prices, which only exist once execution keeps an account view (PR 14).
2. **What happens when strategies share an instrument**, especially when only one of them wants a stop?
3. **How does the portfolio respect [ADR-0021](0021-strategies-see-a-window-handed-in.md)**: a strategy that was not offered an instrument, or that failed, has not decided to sell.

And one practical one: where strategy instances, their parameters and their budgets are configured.

## Decision

1. **Targets are weights of account equity, through risk; execution sizes them.** A strategy's weight is a fraction of its own budget. Portfolio construction turns it into a fraction of account equity: `budget × weight`, exact `Decimal`. The risk gate works in weights too (risk per trade becomes `weight ≤ risk_per_trade × price ÷ (price − stop)`; maximum position size is already a weight). Execution (PR 14) is the single place where approved weights become whole shares, using the account's equity, settled cash and costs, always rounding down. Rounding down after risk can only shrink a position, so it can never break a risk limit.
2. **Each strategy has a sleeve.** The `TargetPortfolioEvent` lists one `Sleeve` per strategy: its budget, its version, whether it decided or failed this cycle, and the instruments it decided on (those it was offered). Tyche will track each strategy's holdings in its own sleeve; orders are netted across sleeves (PR 14).
3. **An instrument's target is the sum of contributions, and each contribution keeps its own stop.** If strategy A wants 0.3 of equity in SPY with a stop at 95 and strategy B wants 0.2 with no stop, SPY's target is 0.5, made of two contributions. Risk sizes each contribution by its own stop, and execution places one stop order sized to A's shares only. Each strategy behaves as it would alone.
4. **Holding is explicit, and needs no memory.** For each sleeve and instrument, execution reads the event this way:
   - the instrument has a contribution from the sleeve: that weight (zero means sell the sleeve's shares);
   - the sleeve decided and the instrument was offered to it but not targeted: zero;
   - otherwise (not offered this cycle, or the sleeve failed): **keep the sleeve's current shares**.
   The portfolio stage therefore keeps no state between cycles, and a restart cannot turn "keep" into "sell".
5. **There is nothing else to resolve.** Positions are long only and every weight is a fraction of a separate budget, with budgets adding up to at most 1. Two strategies' wishes for one instrument add; they cannot exceed equity. A strategy that wants out while another wants in nets out in execution, as one order. The catalog's `conflicts_resolved` field is dropped.
6. **A wiring mistake halts the run.** A `SignalsReadyEvent` that names a strategy without a budget, or misses one that has a budget, or a signal from another decision time, is a bug and halts the run (fail closed, ADR-0003).
7. **Strategies are configured in the workspace**, as the [system overview](../architecture/system-overview.md#7-where-state-lives) describes:
   - `config/tyche.toml` gains a `[strategies]` table: strategy id to budget, as exact decimal strings. Each budget is above 0 and at most 1; together at most 1. The rest is cash.
   - Each id has a `config/strategies/<id>.toml`: the `plugin` to use and its `[parameters]`.
   - Plugins are looked up in a registry in `tyche.strategies`. Each plugin declares its parameters as a strict pydantic model, so a typo or a wrong type stops Tyche with the file and key named. The config hash covers both files.
   - Only built-in plugins can be named. Loading plugin code from the workspace's `strategies/` folder waits until there is a review step for it, because a strategy drafted by an agent is untrusted code (system overview, section 9, note 8).

## Alternatives considered

- **Share quantities in portfolio construction.** What the catalog said. It would move the account view and `AccountEvent` from PR 14 into PR 13, and risk shrinking quantities after sizing would have to round again.
- **One stop per instrument** (for example the highest). Fewer orders, but a strategy that never asked for a stop would get one, and its results in a shared portfolio would differ from its results alone.
- **Carry over a sleeve's last targets in the portfolio stage.** Keeps "hold" out of the event, but it is state the stage would lose on every restart, and a lost "hold" becomes a sale.
- **Orders per sleeve, not netted.** Simpler bookkeeping, but two strategies trading one instrument in opposite directions would pay two minimum commissions, about 1% of a small order each side (ADR-0020).

## Consequences

- PR 13 does not depend on the account; it is pure and tested with events alone.
- Execution (PR 14) needs a position book per sleeve, and a rule for splitting a netted fill between the sleeves whose wishes it served. That rule is decided in PR 14, where fills arrive.
- An instrument can carry more than one resting stop order, one per sleeve that asked for a stop; each that triggers pays its own commission.
- The risk gate will state its limits as weights. The daily loss limit and the drawdown kill switch are account-level and unaffected.
- Adding a built-in strategy means one file in `tyche.strategies`, one registry line and its config files. No core change.
- Plugin parameter models use pydantic, inside `tyche.strategies`. The core still never imports pydantic (ADR-0017).

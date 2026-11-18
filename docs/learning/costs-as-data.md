# Costs as data, and rounding against yourself

## The problem

A backtest that ignores costs is a fantasy, and a backtest with *wrong* costs is worse, because it looks careful. Three things go wrong easily:

1. **The numbers are remembered, not checked.** Broker prices change. A commission written into code in 2026 is still there in 2028, silently wrong, and nobody can tell which backtests used it.
2. **The shape is simplified away.** "0.1% per trade" sounds reasonable and hides the rule that matters most for a small account: IBKR's USD 1.00 minimum per order. On a USD 150 order, that minimum is 0.67%, not 0.1%.
3. **Small errors all lean the same way.** Rounding a fee down, filling exactly at the open, spending cash before it settles: each one is tiny, and each one makes the strategy look a little better. Thousands of trades later, the edge you measured may be made of rounding.

## The idea

**Treat costs as dated data, and make every uncertain choice cost you rather than help you.**

- **The rates live in config**, in `config/costs/US.toml` in the workspace, not in code. The file records `checked_on`, the day the rates were compared with the broker's published schedule, and the config hash covers it. A backtest's run record therefore says exactly which prices it assumed.
- **The shape is the broker's own formula**, tested against the broker's own published examples. If IBKR says 10 shares of a USD 0.20 stock cost USD 0.02, there is a test that says so.
- **Decimals are written as strings** (`"0.005"`). TOML reads `0.005` without quotes as a binary float, which cannot hold most decimal fractions exactly. The loader refuses an unquoted number rather than convert it.
- **When unsure, overstate the cost.** Regulatory fees are rounded *up* to the cent. Slippage always moves the price against the order. A purchase may use settled cash only, the stricter of IBKR's two statements. If the live account turns out to be cheaper, that is a pleasant surprise; the reverse would be a loss.
- **Time is a cost too.** In a cash account, sale proceeds cannot be spent until they settle (T+1). A rotation that sells and buys therefore takes two sessions, and the backtest must pay that delay just as the live account will.

This is the same discipline as [lookahead bias](lookahead-bias.md), applied to money instead of time: never let the simulation know or have something the live account would not.

## Where it is in Tyche

| Piece | Where |
|---|---|
| The checked facts, with sources | [IBKR Canada: costs and settlement](../developer-guide/ibkr-canada-costs-and-settlement.md) |
| The decision | [ADR-0020](../adr/0020-cost-and-settlement-model.md) |
| Commission, fees, slippage, whole-share sizing | `tyche.core.domain.costs` |
| Settlement date (T+n sessions) | `tyche.core.sim.settlement` |
| The rates, per market profile | `config/costs/US.toml` in the workspace; the template is in `tyche.config.templates` |
| Strings-only decimals in config | `ExactDecimal` in `tyche.config.loader` |

## What it costs

- **Backtests look worse.** That is the point, but it is still discouraging: a strategy that rotates five small positions monthly pays about 16% a year in commissions alone at this account size.
- **The rates go stale.** A dated config file makes staleness visible; it does not prevent it. `tyche config check` prints the date, and the rates must be checked again before paper trading and before going live.
- **Being conservative can reject a good strategy.** If the real costs are lower than modelled, a marginal strategy may be discarded. Paper trading (Phase 2) measures the difference.

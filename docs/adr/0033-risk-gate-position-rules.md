# ADR-0033: The risk gate's position rules: what it cuts, in what order, and how it says so

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-23

## Context

[ADR-0032](0032-risk-limits-in-three-layers.md) defined the limits; until now nothing applied them, and the gate (`PassThroughGate`) approved every proposed portfolio unchanged. Phase 2, PR 2 makes the gate apply the three **position rules** of the active profile and of each strategy's `[risk]` table: risk per trade, max position size and max open positions. The account rules (the daily loss limit and the drawdown kill) come in PR 4, and a last check on each order against the guardrails' money caps in PR 3.

The gate works in weights of account equity, before execution sizes anything in shares ([ADR-0022](0022-portfolio-targets-as-weights-in-sleeves.md), [ADR-0023](0023-execution-sleeves-stops-and-cash.md)). Several sleeves can target one instrument, and a sleeve keeps what it holds when it does not decide on an instrument.

Four questions came up, and Pablo answered each on 2026-11-23, before any code:

1. **Above max open positions, which targets give way?** Pablo chose: **held positions keep their place, and new entries fill the free places, largest target weight first, ties by symbol**; every blocked entry is recorded. (The alternative ranked holdings and entries together, which could sell a holding to make room for a slightly larger entry.)
2. **An instrument above max position size, with several sleeves in it?** Pablo chose: **every sleeve's contribution shrinks by the same proportion**, each stop still sized to its own sleeve's shares. (The alternative cut the largest contribution first.)
3. **When do the limits apply?** Pablo chose: **max position size at every cycle, to what is held too** (the rebalance band keeps that from churning), and **risk per trade only on entries and additions**, because with a fixed stop it would trim every winner: as the price rises above a fixed stop, the loss to the stop grows, and the allowed position shrinks.
4. **A backtest without `--risk-profile`?** Pablo chose: **it uses `default`**, so a backtest shows what the system would trade. Buy-and-hold then holds 20% SPY, the rotation at most 60%, and this ADR records what that does to the examples. (The alternative required `--risk-profile` on every run.)

## Decision

**The gate only lowers or removes contributions.** It never raises one, adds one, or touches a holding a sleeve keeps without deciding. Approved weights it sets are rounded down to `1e-12` of equity, so rounding can never take a portfolio past a limit; a trillionth of equity is far below one share of anything.

**The rules, in order.** The order matters, and this one is chosen so that a contribution blocked for one reason never takes a place another could have had, and the account-wide shrink sees only what survived the rest:

1. **Each contribution on its own.**
   - A strategy's own `max_position_size`, if it set one, caps its contribution.
   - **Risk per trade**, for a target with a stop that is an entry or an addition (the sleeve wants more weight than it holds now). The loss from the decision's close to the stop may be at most `risk_per_trade` of equity, so the weight is at most `risk_per_trade × close / (close − stop)`, using the stricter of the strategy's and the profile's rate. An addition is never cut below what the sleeve already holds: if the holding alone is past the limit, the addition is refused and the holding kept. A stop at or above the close blocks the entry: the loss to it cannot be bounded.
2. **Open positions per sleeve**, for a strategy with its own `max_open_positions`, then **for the account**, under the profile's. A holding stays if the sleeve keeps it (did not decide on it) or still wants it; a holding the proposal sells to zero frees its place, so a rotation can rotate. New entries fill what is free, largest weight first, ties by symbol and exchange; the rest are blocked. At account level, adding to an instrument another sleeve already holds takes no new place.
3. **Position size for the account.** The profile's `max_position_size` caps each instrument across every sleeve, counting what sleeves keep without deciding. Above it, every contribution shrinks by the same proportion.

**Every change is recorded.** Each cut is a `RiskAdjustment`: the rule, its scope (`strategy` for a limit measured on one sleeve, `account` for one measured across the account), the action (`shrink` or `block`), the sleeve and instrument, the weight before and after, the limit and a sentence of reason. The gate publishes one `RiskEvent` per adjustment, then the `ApprovedPortfolioEvent`, which lists them all in `adjustments` and names the active profile. The event checks that its targets end where its adjustments say.

**The rules are a pure function.** `review(proposal, held weights, closes, limits)` does all of the above with no bus and no state. `RiskGate` is a thin shell around it: it collects the closes and the account snapshot of the same close, turns the sleeve book's shares into weights, calls `review`, and publishes. A decision with no account snapshot of its own close halts the run, as execution does.

**The run applies `RiskLimits`, checked in the core too.** `RiskLimits` bundles the guardrails, the active profile and each strategy's own limits, and refuses a profile above the guardrails or a strategy looser than its profile, even when built without the config layer.

**`--risk-profile` on every backtest command.** `tyche backtest`, `walk-forward`, `sweep` and `capital` take `--risk-profile <name>`, default `default`. The run record gains a `risk` section (the profile's values, each strategy's own limits, the rules applied) and `outcome.risk_adjustments`, the cuts counted by rule and action. The record format stays 1: the fields are added, and a report of an older record says it was recorded before the gate.

**Tests of other mechanics run under a test profile.** The golden-file and reference tests, and the tests of sleeves, stops, costs and sweeps, use `unbound`: risk per trade 100%, position size 100%, 1,000 positions, inside equally wide test guardrails. Under it the gate approves every trade unchanged, so those tests keep checking what they were written to check. The default profile has its own end-to-end test.

### What `default` does to the examples

The same scratch workspace and Yahoo data as [ADR-0027](0027-example-strategies-fixed-in-advance.md), each strategy alone with USD 10,000 from 2005-01-03 to 2023-12-29. Under `unbound` all three reproduce their earlier results to the cent (buy-and-hold 52,168 USD, the rotation 30,049, the mean reversion 12,735), which confirms the gate changes nothing when its limits do not bind.

| | Buy-and-hold SPY | Trend rotation | Mean reversion |
|---|---|---|---|
| Final equity | 14,568 USD (was 52,168) | 23,464 USD (was 30,049) | 10,650 USD (was 12,735) |
| CAGR | 2.00% (was 9.09%) | 4.59% (was 5.97%) | 0.33% (was 1.28%) |
| Volatility | 3.69% | 8.50% | 2.03% |
| Sharpe (rf 0) | 0.56 (was 0.57) | 0.57 (was 0.49) | 0.17 (was 0.27) |
| Max drawdown | 13.19% (was 53.23%) | 15.10% (was 29.68%) | 5.98% (was 12.44%) |
| Exposure | 19.34% | 54.99% | 3.96% |
| Fills; costs | 98; 99 USD | 434; 450 USD | 677; 696 USD |
| What the gate cut | position size, at every close (4,781) | position size (13,239) | position size (971), risk per trade (721) |

No free riding in any run. Nothing was blocked: no run wanted more than five instruments.

## Alternatives considered

- **Risk per trade on every holding, at every cycle.** Simpler, but with a fixed stop it trims every winner as its price rises (Pablo's decision 3).
- **Risk per trade on the shares added only.** "Per trade" read literally. Repeated additions could then each risk the full rate; the whole position's loss to its stop is the quantity that matters, so the gate bounds that, at the decision's close.
- **Cap held positions through execution instead.** Execution works in shares and knows nothing of profiles; the gate is the one place limits live ([ADR-0006](0006-target-positions-with-optional-stops.md)).
- **Count open positions after the size cap.** Then an entry blocked by its stop could take a place another entry could have used.
- **One `RiskEvent` per decision, holding every adjustment.** Fewer events, but the journal and the notifier would have to unpack them; one event per cut is what the catalog planned and what a reader looks for.

## Consequences

- **Every run now trades within a profile.** A backtest's numbers depend on `--risk-profile`, and the record says which. Results recorded before this change used no limits.
- **`default` makes the examples small.** Buy-and-hold at 20% earns about a fifth of SPY's return with about a quarter of its drawdown, and its Sharpe ratio is unchanged: the same asset, held smaller, with the rest in cash that earns nothing in the simulator ([ADR-0025](0025-metrics-against-the-benchmarks-total-return.md)). A strategy is judged against buy-and-hold, so comparisons should hold the risk profile fixed on both sides; PR 5 runs profiles side by side.
- **The cap trims on drift, in whole shares.** A position at its 20% cap that rises is trimmed once it passes the rebalance band; with few shares, one share of rounding can push it past. Buy-and-hold went from 3 fills to 98 under `default`.
- **A capped position emits a `RiskEvent` every cycle.** A strategy that keeps asking for more than the cap is cut, and recorded, at every close (4,781 times for buy-and-hold over 19 years). That is honest, but the Discord summary (PR 16) will need to report cuts as counts, not one message each.
- **Small accounts hold less, or nothing.** With USD 1,000, 20% is below one share of SPY at about USD 300, so buy-and-hold never buys. The small-account profile is PR 5's decision ([ADR-0031](0031-minimum-viable-capital.md)).
- **Costs weigh more on smaller positions.** The mean reversion's costs (696 USD) now exceed its gain (650 USD), because the minimum commission does not shrink with the order.
- **What a profile does not yet cover:** drift of a holding no sleeve decided on this cycle is only limited when some sleeve targets that instrument again; the daily loss limit, the drawdown kill (PR 4) and the money caps on orders (PR 3) are not applied yet.

# ADR-0031: Minimum viable capital: a size penalty against a large reference account, Fixed against Tiered

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-22

## Context

Phase 1, PR 22 delivers what the Phase 0 review agreed for a small account ([system overview, note 1](../architecture/system-overview.md#9-assumptions-and-honest-notes)): "a minimum viable capital analysis: the account size at which each strategy's edge survives costs. If five positions under $1,000 CAD cannot work, the analysis will say so and propose different defaults (fewer positions, lower turnover or more capital)." [ADR-0020](0020-cost-and-settlement-model.md) added a second commitment: compare IBKR Pro Fixed with Tiered under a stated exchange-fee assumption, so that Pablo can choose the plan for the real account.

Two effects make a small account expensive, and neither is in a strategy's rules. Fixed's USD 1.00 minimum per order is a large fraction of a small order. Whole shares (IBKR's API cannot place fractional orders) leave part of every small target in cash, or all of it when one share costs more than the target.

Four questions came up, and Pablo answered each one, the first three on 2026-11-22 before any code:

1. **What test decides that an amount is enough?** The size penalty against a large reference account (below), not "beats SPY after costs" and not "costs under a quarter of the profit before costs".
2. **The backtests trade at 2005 to 2023 prices, and most of these ETFs have never split, so their shares cost more today.** Add a check of the latest cached close, even though that bar is inside the holdout.
3. **Should the runs also vary the number of positions** (the trend rotation's `holdings`)? No: only the capital changes, so no trial is added; the effect of fewer positions is shown as arithmetic.
4. **How large should the reference account be?** It was first USD 1,000,000. On real data that was too large for the trend rotation (see below), and on 2026-11-23 Pablo chose USD 100,000, with a check that flags any reference whose orders the volume cap cut short.

## Decision

1. **`tyche capital --from <date>`** runs each configured strategy **alone, with a budget of the whole account and its configured parameters**, as a backtest over the same days at each amount (`--amounts`, default USD 500, 1,000, 2,000, 5,000, 10,000 and 25,000) and on a **reference account** (`--reference`, default USD 100,000), through the same path as `tyche backtest`. Only the starting cash and the pricing plan change between runs.
2. **The size penalty** of an amount is the reference run's CAGR minus the amount's, both after costs, under the same plan. An amount is **viable** when its penalty is within a tolerance (`--tolerance`, default half a point a year). The **minimum viable capital** is the smallest amount tested from which every larger amount tested is viable too; none if the largest is not.
3. **The edge is reported beside it, never folded into it.** The size penalty says what account size costs; whether there is an edge worth keeping is whether the strategy beats its benchmark (ADR-0025), shown for the reference account and at the minimum. A strategy that trails the benchmark even on the reference account is reported as having no edge to keep, whatever its minimum.
4. **Both plans run.** Fixed is the costs file's `[commission]`, as before; Tiered is a new, optional `[tiered]` table in the same file with the date it was checked. Backtests, walk-forwards and sweeps keep using `[commission]`. Tiered is modelled as `TieredSchedule`: the first volume tier's commission (USD 0.0035 a share, minimum USD 0.35, maximum 1% of value), NYSE and FINRA pass-through fees as fractions of it, NSCC/DTC clearing (USD 0.0002 a share, at most 0.5% of value), and an **assumed exchange fee of USD 0.0030 a share**: what NYSE Arca and Nasdaq charge to remove liquidity, against USD 0.0015 in their opening auctions. Where a SmartRouted order at the open executes is not published, so Tyche takes the higher figure. Rates checked on 2026-11-22 ([IBKR facts](../developer-guide/ibkr-canada-costs-and-settlement.md)).
5. **Today's share prices** are read from the cache: each candidate's latest close and its date, and how many whole shares one of `--positions` equal positions (default 5, the brief's default risk profile) buys at each amount. That close may lie inside the holdout. **It is the one read of a holdout bar Tyche makes**, and it reads the price only: nothing is run on it, and the record says so. Prices do not describe any strategy's results, so this spends none of the holdout's value as an untouched test.
6. **What one round trip costs** is shown as arithmetic, not backtested: buying one position and selling it again at USD 100 a share, commission, fees and slippage, as a share of the position, for each amount split into 1 to `--positions` positions, under each plan.
7. **What an analysis keeps.** `reports/capital/<id>/capital.json`: the code, the config hash and every setting, the request, each plan's rates, every run's figures, each verdict, the arithmetic and today's prices; and `report.html`, built from it alone. No run's equity or fills are kept; each can be run again from its amount, plan and the config hash. Each strategy is **one trial**, with the `trial_key` of its configured parameters: running it at several sizes is not choosing between versions of it. A strategy already backtested with those parameters adds nothing to the count.
8. **Amounts are in the profile's cash currency** (USD for `US`). Currency conversion is not modelled (ADR-0020). Pablo's CAD 1,000 is converted in the docs at a dated Bank of Canada rate: 1.4325 CAD per USD on 2026-11-20, so about USD 698.

## Implementation choices made in PR 22, for review there

- **Viable within the tolerance either way.** The question asked for a CAGR "within half a point" of the reference. The first run on real data showed why that must hold in both directions: over 2020 and 2021, buy-and-hold of SPY at USD 300 could not buy a share at about USD 320, bought one when SPY fell below USD 300 in March 2020, and beat the large account by 6.8 points a year. That is a different strategy (wait in cash for a crash), lucky once. A result that size moves a lot either way is not the strategy that was designed.
- **The reference runs first** for each strategy and plan, so missing history stops the analysis early and each later run's penalty can be printed as it is measured.
- **"Short of a share"** counts the decisions at which some target was worth less than one whole share (`PlanNote.BELOW_ONE_SHARE` in an `ExecutionPlanEvent`).
- **An absent optional table is left out of the config snapshot and hash** (`model_dump(exclude_none=True)`). No config file held a `None` before, so no existing hash changes; checked on a workspace without `[tiered]`, which hashes the same with this code and with `main`'s.
- **A reference account can be too large.** The simulator fills at most 1% of a bar's volume. Each run counts its orders that expired with shares unfilled (`cut_short`). If the reference run has any, the strategy's answer under that plan is withheld, in the terminal and the report, with a warning to run again with a smaller `--reference`.
- **Tiered's third-party fees are added on top of the 1% maximum**, because IBKR does not say whether the maximum covers them. That overstates Tiered when it does. Only the first volume tier is modelled: a small account trades far fewer than its 300,000 shares a month.

## Checked on real data

Yahoo data in a scratch workspace, 2005-01-03 to 2023-12-29, the three strategies each alone with their configured parameters, at USD 500, 700 (about CAD 1,000 at 1.4325), 1,000, 2,000, 5,000, 10,000 and 25,000, against a USD 100,000 reference, under Fixed and Tiered: 48 backtests in about 20 minutes. The benchmark, SPY's total return, had a CAGR of 9.59% and a Sharpe ratio of 0.57.

**The first reference was too large.** With USD 1,000,000, the trend rotation's three positions were about USD 333,000 each, and the volume cap cut 22 of its orders short. Its result on that account (6.84%) was below what USD 25,000 and 100,000 earned (7.43% and 7.66%), so no amount was within half a point and the answer was "none". At USD 100,000 none of the three strategies had an order cut short, and at USD 1,000,000 only the rotation did.

| Minimum viable capital | Fixed | Tiered | On the reference account | Beats SPY? |
|---|---|---|---|---|
| Buy-and-hold (SPY) | USD 700 | USD 700 | 9.11% a year, Sharpe 0.57 | It is SPY, less cash |
| Mean reversion | USD 10,000 | USD 5,000 | 1.54% a year, Sharpe 0.31 | No: there is no edge to keep |
| Trend rotation (3 holdings) | USD 25,000 | USD 25,000 | 7.66% a year, Sharpe 0.60 | Not on CAGR (2 points behind); a Sharpe ratio 0.03 higher, in-sample, which the walk-forward did not confirm (ADR-0029) |

At USD 700, roughly CAD 1,000:

| At USD 700 | CAGR, Fixed | Costs a year, Fixed | CAGR, Tiered | Costs a year, Tiered |
|---|---|---|---|---|
| Buy-and-hold | 8.85% | 0.01% | 8.85% | 0.01% |
| Mean reversion | -3.55% | 5.62% | -0.61% | 2.30% |
| Trend rotation | 3.03% | 3.25% | 5.44% | 1.14% |

- **Five positions under CAD 1,000 does not work.** Each position would be about USD 140. One round trip of one position costs 2.12% of it under Fixed and 0.84% under Tiered (USD 100 a share), and four of the nine candidates (SPY at USD 690, QQQ at 608, GLD at 323, IWM at 257 on 2026-11-20) cost more than USD 140 a share, so they cannot be held at all. Even split three ways, as the rotation does, it lost 4.6 points a year to its size under Fixed.
- **Tiered is much cheaper for a small account**, even with the exchange fee overstated: it cut the rotation's costs at USD 700 from 3.25% to 1.14% a year and the mean reversion's at USD 1,000 from 4.57% to 2.03%. From USD 25,000 the two plans cost about the same.
- **The rotation's answer is noisy between USD 2,000 and 10,000.** Its CAGR went 5.53%, 6.43%, 5.97% (Fixed) as the account grew: whole shares and the rebalance band send each size down a slightly different path of trades. A half-point tolerance is tighter than that noise, so only USD 25,000 passed. "USD 25,000" means "more than USD 10,000, and 25,000 is the next size tested".
- **The mean reversion has no edge at any size**, so its minimum is academic. It trades often, so its costs fall steadily with size: from 6.38% a year at USD 500 to 1.01% at USD 25,000 under Fixed. Even on the reference account they take 0.96% a year, mostly slippage.
- **Buy-and-hold is viable from USD 700 on 2005 prices**, when SPY cost about USD 120. Today a share costs USD 690: USD 700 holds one share and USD 500 none.

**Proposed defaults**, for Pablo to decide; nothing in the code or the configuration changes with them. Accepting this ADR accepted the analysis, not these defaults: they remain open, for the Phase 2 risk profiles (`STATUS.md`).

1. **Use Tiered for the real account.** At these sizes it cut costs by a half to two thirds. The live risk profile and the costs file are Pablo's to change (`CLAUDE.md`, rule 3).
2. **Under about USD 5,000 (CAD 7,000), hold one or two positions, not five.** With one position, a round trip costs 0.44% of USD 700 under Fixed and 0.23% under Tiered, against 2.12% and 0.84% split five ways. The brief's default risk profile (at most five positions, at most 20% of equity each) cannot be fully invested with fewer than five positions; a small-account profile would need a larger single-position limit. That is a Phase 2 risk-profile decision.
3. **Prefer low turnover below USD 10,000.** Of the two examples, the monthly rotation (about 9 closed trades a year) survives size far better than the mean reversion (about 17, 328 from 2005 to 2023 in PR 18).
4. **For a several-ETF rotation like the example, plan on at least USD 25,000 (about CAD 36,000)**, or accept a measured size penalty: about 1 to 2 points a year between USD 2,000 and 10,000 under Tiered.

## Alternatives considered

- **"Beats SPY after costs" as the test.** Simple and strict, but the example strategies trail SPY at every size, so it answers "no size works" and says nothing about what size costs. Kept as the separate edge check (decision 3).
- **Costs as a share of the profit before costs**, viable under 25%. Undefined when a strategy loses before costs, and blind to whole shares, which cost through cash left idle, not through fees.
- **Varying the number of positions in the backtests.** A more direct answer for the trend rotation, but each `holdings` value is a new trial, counted for good (ADR-0030), and choosing `holdings` from these results is a fit to history. The arithmetic shows what fewer positions does to costs without that.
- **Historical prices only**, reading nothing after 2023. Keeps the holdout untouched, but hides the biggest effect for a small account today: an ETF whose share costs more than one position cannot be held at all.
- **The last pre-holdout close (2023-12-29) for today's prices.** No holdout data read, but prices almost three years old.
- **Fractional shares**, as a "what if". IBKR's API cannot place them (ADR-0020), so a result that depends on them is one Tyche could not trade.

## Consequences

- Each strategy now has a stated minimum account under each plan, and a separate statement of whether it has an edge.
- Pablo can choose Fixed or Tiered for the real account from runs at the sizes that matter, and the choice is his. Moving backtests to Tiered would be a change to `[commission]` in his workspace.
- The holdout has one stated, narrow exception: the latest close is read for its price. Any further read of holdout bars needs its own decision.
- The tolerance is a choice, not a fact: a looser one gives smaller minimums. The record states it.
- Running a strategy beside others gives it only its budget, so its own minimum is the amount divided by its budget. The report says so.

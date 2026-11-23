# Minimum viable capital

How much money does a strategy need before its account size stops hurting it? `tyche capital` answers that for each of your strategies, under IBKR Pro Fixed and under Tiered, so you can also choose a pricing plan for the real account.

A small account pays more for the same trades, for two reasons:

- **The minimum commission.** Fixed charges at least USD 1.00 an order, Tiered at least USD 0.35 plus fees. On a USD 140 position that is a large fraction of every trade.
- **Whole shares.** Tyche can only hold whole shares. A USD 140 target in an ETF priced at USD 600 is zero shares: the strategy decided to hold it, and the account cannot.

Both fade as the account grows. `tyche capital` runs each strategy at several account sizes and on a very large reference account, where they no longer matter, and compares. The learning note [what account size costs](../learning/account-size.md) explains the idea.

Everything on the [backtest page](03-running-a-backtest.md) applies: the holdout, the candidates, the benchmark, fetching history first.

## Run

```bash
uv run tyche capital --from 2005-01-03
```

| Option | Default | Meaning |
|---|---|---|
| `--from` | (required) | First session date to trade |
| `--to` | the day before the holdout | Last session date to trade |
| `--amounts` | `500,1000,2000,5000,10000,25000` | Starting cash to test, smallest first, in the profile's currency (USD) |
| `--reference` | `100000` | The large account every amount is compared with. Too large, and the cap on a bar's volume distorts it: Tyche warns when that happens |
| `--tolerance` | `0.5` | How far an amount's CAGR may be from the reference's, either way, in points a year |
| `--positions` | `5` | The most positions the round-trip arithmetic and today's share check split an account into |
| `--risk-profile` | `default` | The risk profile every run applies, a file in `config/risk/`. Under `default` a position is at most 20% of the account, so a small account may hold nothing | The figures on this page were recorded before the risk gate applied limits (Phase 2, PR 2); under `default` they are smaller ([risk profiles](08-risk-profiles.md#expect-smaller-numbers-under-default)). |

**Every strategy with a budget** under `[strategies]` in `config/tyche.toml` is analysed, each **alone, with the whole account**, with the parameters in its strategy file. The budget's size does not matter here, only that there is one. To analyse the example strategies, give them a budget first.

**Your money is in CAD; the amounts are in USD**, because the `US` profile trades in USD. Convert at today's rate: on 2026-11-20 the Bank of Canada's rate was 1.4325 CAD per USD, so CAD 1,000 was about USD 698. To include your own amount:

```bash
uv run tyche capital --from 2005-01-03 --amounts 500,700,1000,2000,5000,10000,25000
```

Each amount runs once per plan, plus the reference, so the analysis runs `(amounts + 1) × plans × strategies` backtests. With the seven amounts above, two plans and the three example strategies, that is 48 backtests, about 20 minutes. It prints one line per run as it goes, the reference first, then the answer:

```text
  trend_rotation   IBKR Pro Fixed      100,000  CAGR    7.66%  costs   0.34% a year  (reference)
  trend_rotation   IBKR Pro Fixed          500  CAGR    1.55%  costs   3.43% a year  penalty   +6.11 pts
  trend_rotation   IBKR Pro Fixed          700  CAGR    3.03%  costs   3.25% a year  penalty   +4.63 pts
  ...
Capital 20261123T060408Z-9f0ec5d2: minimum viable capital, by strategy and plan
  buy_and_hold     IBKR Pro Fixed   700 USD; reference Sharpe 0.57, benchmark 0.57
  buy_and_hold     IBKR Pro Tiered  700 USD; reference Sharpe 0.57, benchmark 0.57
  mean_reversion   IBKR Pro Fixed   10,000 USD; reference Sharpe 0.31, benchmark 0.57
  mean_reversion   IBKR Pro Tiered  5,000 USD; reference Sharpe 0.31, benchmark 0.57
  trend_rotation   IBKR Pro Fixed   25,000 USD; reference Sharpe 0.60, benchmark 0.57
  trend_rotation   IBKR Pro Tiered  25,000 USD; reference Sharpe 0.59, benchmark 0.57
```

If the reference account is so large that the simulator's cap on a bar's volume cuts some of its orders short, the answer for that strategy is withheld (`not judged: the reference account is too large`) with a warning: run again with a smaller `--reference`.

## Pricing plans

Fixed comes from `[commission]` in `config/costs/US.toml`, as for every backtest. Tiered comes from a `[tiered]` table in the same file. New workspaces have it; **an older workspace needs it copied** from a new one (`tyche init --home <scratch-folder>`), or `tyche capital` runs Fixed only. Backtests, walk-forwards and sweeps never use `[tiered]`.

Tiered's total cost depends on where each order executes. The table assumes an exchange fee of USD 0.0030 a share, what NYSE Arca and Nasdaq charge to remove liquidity. Their opening auctions charge USD 0.0015, so if Tyche's orders at the open execute there, Tiered is a little cheaper than shown. The [IBKR facts page](../developer-guide/ibkr-canada-costs-and-settlement.md) has the sources.

## What the numbers mean

**Size penalty**: the reference account's CAGR minus this amount's, after costs, under the same plan. Positive when the smaller account earns less.

**Viable**: the size penalty is within the tolerance **either way**. A small account that does much *better* than the large one is not viable either. It was running a different strategy, because whole shares changed what it could hold, and its lead was luck. (Over 2020 and 2021, USD 300 could not buy one share of SPY, bought one in the March 2020 crash, and beat the large account by almost 7 points a year.)

**Minimum viable capital**: the smallest amount from which every larger amount tested is viable. One good result below a failing one does not count. "None of the amounts tested" means even the largest amount loses more than the tolerance to its size.

**The edge is a separate question.** The minimum says what size costs a strategy. Whether the strategy is worth running at all is whether it beats the benchmark, shown beside the minimum as the reference account's Sharpe ratio against SPY's. A strategy that trails SPY even on USD 100,000 has no edge for a small account to keep.

**Running beside others.** Each strategy is analysed with the whole account. Beside other strategies it gets only its budget, so its own minimum is the amount divided by its budget: a strategy viable from USD 5,000, given half the account, needs USD 10,000.

## Two tables of arithmetic

**What one round trip costs**: buying one position and selling it again, as a share of the position, for each amount split into 1 to 5 equal positions, at USD 100 a share. No backtest: commission, fees and slippage on both orders. A strategy that turns every position over once a month pays twelve of these a year.

**Today's share prices**: the backtests trade at 2005 to 2023 prices. Most of these ETFs have never split, so their shares cost much more now, and whole shares bind harder today than the backtests show. This table reads each candidate's latest cached close and shows how many whole shares one of five equal positions buys at each amount. A zero means that ETF cannot be held at that size. Fetch recent data first (`tyche data fetch`) for it to mean today.

That close lies inside the holdout. It is the one exception Tyche makes: only the price is read, and nothing is run on it ([ADR-0031](../adr/0031-minimum-viable-capital.md)).

## The record and the report

Every analysis writes `reports/capital/<id>/`:

| File | Holds |
|---|---|
| `capital.json` | What ran (code, config hash and every setting, the amounts, the tolerance, each plan's rates), every run's figures, each answer, the arithmetic and today's prices |
| `report.html` | The report, built from that file alone |

No run keeps its equity or fills. Each strategy counts as **one trial** (its configured parameters), and a strategy you have already backtested with those parameters adds nothing to the count.

`report.html` opens with each strategy's answer under each plan, then:

| Section | Shows |
|---|---|
| The answer | Each strategy and plan: the minimum, the reference account's CAGR and Sharpe ratio, the CAGR at the minimum and its difference from the benchmark |
| One section per strategy | Every amount: CAGR, size penalty, viable or not, costs a year, cost drag, Sharpe ratio, exposure, how often a target was short of a share, and the difference from the benchmark |
| What one round trip costs | The arithmetic above, per plan |
| Today's share prices | The whole-share check above |
| What ran | The code, the config hash, the rule, the tolerance and each plan's rates |
| Data and its limits | The limits every backtest shares, and six this analysis adds |

`tyche report <id>` rebuilds it.

## What it found on real data

The run above, 2005 to 2023, in a scratch workspace. [ADR-0031](../adr/0031-minimum-viable-capital.md) has the full figures.

| Strategy | Minimum, Fixed | Minimum, Tiered | Beats SPY? |
|---|---|---|---|
| Buy-and-hold of SPY | USD 700 | USD 700 | It is SPY, less the cash left over |
| Mean reversion | USD 10,000 | USD 5,000 | No, at any size |
| Trend rotation, 3 holdings | USD 25,000 | USD 25,000 | No: 2 points a year behind on CAGR |

**Five positions under CAD 1,000 does not work.** Five positions of about USD 140 each pay 2.12% of a position for every round trip under Fixed, 0.84% under Tiered, and SPY, QQQ, GLD and IWM cost more than USD 140 a share today, so they cannot be held at all.

**Tiered is the cheaper plan for a small account.** At USD 700 it cut the rotation's costs from 3.25% to 1.14% a year.

**Proposed, for you to decide** (nothing changes until you do):

1. Choose Tiered for the real account.
2. Under about USD 5,000 (CAD 7,000), hold one or two positions, not five. That needs a small-account risk profile in Phase 2 with a larger single-position limit than the default 20%.
3. Below USD 10,000, prefer strategies that trade rarely.
4. A rotation across several ETFs, like the example, needs about USD 25,000 (CAD 36,000) to run as designed.

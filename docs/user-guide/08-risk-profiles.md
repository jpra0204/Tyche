# Risk profiles and guardrails

This page explains the three files that hold Tyche's risk limits, how to make a new risk profile, how to check them, and what they do to a backtest. The decisions behind them are in [ADR-0032](../adr/0032-risk-limits-in-three-layers.md), [ADR-0033](../adr/0033-risk-gate-position-rules.md), [ADR-0015](../adr/0015-daily-loss-limit.md) and [ADR-0035](../adr/0035-account-rules-and-the-drawdown-halt.md).

> **What works today.** Tyche reads and checks these files every time it starts, and refuses to start if one breaks a limit. **The risk gate applies the position rules** (risk per trade, max open positions, max position size) and **the account rules** (the daily loss limit and the drawdown kill) to every backtest. **Execution enforces long only and no leverage** in every run, and the **money caps** in paper and live (not in research backtests; see below). Not yet: lifting a drawdown halt by hand, which arrives with the kill switch (Phase 2, PR 8). Until then a halt lasts to the end of the run.

## The three layers

Each layer may only be stricter than the one above it.

| File | Holds | Who edits it |
|---|---|---|
| `config/guardrails.toml` | The hard limits: long only, no leverage, a ceiling for every profile limit, and money caps per currency | Only you |
| `config/risk/<name>.toml` | One named risk profile per file. The file name is the profile's name | You |
| `[risk]` in `config/strategies/<id>.toml` | Optional, stricter position limits for one strategy | You |

Fractions are of account equity and written as strings so they stay exact: `"0.20"` is 20%.

### A risk profile

`tyche init` ships `config/risk/default.toml` with the brief's defaults:

| Key | Default | Meaning |
|---|---|---|
| `risk_per_trade` | `"0.01"` | The most one position may lose before its stop triggers. Only for positions that carry a stop |
| `max_open_positions` | `5` | How many instruments may be held at once, across all strategies |
| `max_position_size` | `"0.20"` | The largest single position |
| `daily_loss_limit` | `"0.03"` | A loss of at least this from one close to the next blocks new entries and additions at that close; exits still go through |
| `drawdown_kill` | `"0.15"` | A fall of at least this from peak equity halts everything until you restart by hand |

### The guardrails

Every profile key has a ceiling in `config/guardrails.toml` (`max_risk_per_trade`, `max_open_positions`, `max_position_size`, `max_daily_loss_limit`, `max_drawdown_kill`), so no profile can switch a protection off.

The money caps are listed **per currency**, because Tyche cannot convert between currencies until Phase 4:

```toml
max_total_capital = [
    { amount = "700", currency = "USD" },
]
max_order_value = [
    { amount = "350", currency = "USD" },
]
```

The `US` market profile holds USD, so it needs a USD cap in both lists. Each order cap must be at most the capital cap in the same currency.

The values `tyche init` writes are an example, not advice. Set your own. Agents may propose a change to this file in writing; they never apply one.

#### What the money caps do

They describe the real account, so they apply in **paper and live trading only**. Research backtests (`backtest`, `walk-forward`, `sweep`) keep their own `starting_cash`; to see what a small account does to a strategy, run `tyche capital` at your sizes ([ADR-0034](../adr/0034-order-level-guardrails.md)).

When they apply:

- **Tyche trades as if the account were worth at most `max_total_capital`.** A 20% position is 20% of the cap, even if the account holds more. Money above the cap, gains included, stays in cash until you raise the cap.
- **Each purchase is cut to fit** `max_order_value`, and all of them to what is left under `max_total_capital`, valued at the last close plus the price buffer. A purchase not one share of which fits is not sent. Sales are never cut.
- **Every cut is recorded** as a `RiskEvent` and counted in the run's record.

So `max_order_value` must be at least the price of one share of anything you want to hold, plus the 2% buffer, or that fund can never be bought.

**Raising a cap** is how more money goes to work. Do it by hand, in your workspace's history, with the reason.

### A strategy's own limits

To hold a strategy to tighter limits than the profile, add a `[risk]` table to its file. Each key is optional:

```toml
# config/strategies/mean_reversion.toml
[risk]
risk_per_trade = "0.005"
max_position_size = "0.10"
max_open_positions = 2   # in this strategy's own positions
```

Only these three can be set per strategy. The daily loss limit and the drawdown kill are measured on the whole account.

## Making a new profile

1. Copy the default profile under a new name. Names are lower case, with digits, `_` or `-`, starting with a letter:

   ```bash
   cp ~/tyche-workspace/config/risk/default.toml ~/tyche-workspace/config/risk/safecash.toml
   ```

2. Edit the values in the new file.
3. Check it:

   ```bash
   uv run tyche config check --risk-profile safecash
   ```

   You should see `Configuration is valid` and a `Risk profile:   safecash: ...` line with your values.

## Checking

`tyche config check` checks every profile against the guardrails, and each strategy's own limits against the active profile (`default` unless you pass `--risk-profile`). It prints:

```text
  Risk profile:   default: risk per trade 0.01, 5 positions, position size 0.20, daily loss 0.03, drawdown kill 0.15
                  also within the guardrails: safecash
  Guardrails:     long only, no leverage; capital 700 USD, order 350 USD
                  (applied: risk per trade, positions, position size, the daily loss limit and the drawdown kill in every run; long only and no leverage in every run; the money caps in paper and live)
```

A breach stops Tyche, naming the file, the key, its value and the limit:

```text
Error: config/risk/safecash.toml: a risk profile may not exceed the guardrails (config/guardrails.toml)
  max_position_size = 0.30 is above max_position_size = 0.25
```

Fix the value, or the limit above it if you meant to change that, and check again.

## What a profile does to a backtest

Every backtest command runs under a risk profile: `tyche backtest`, `tyche walk-forward`, `tyche sweep` and `tyche capital` all take `--risk-profile <name>`, and use `default` without it. `tyche compare-profiles` takes several (below).

```bash
uv run tyche backtest --from 2005-01-03 --risk-profile safecash
```

The risk gate sits between what the strategies want and what is traded. It only ever trades **less** than the strategies asked for:

| Rule | What the gate does |
|---|---|
| `risk_per_trade` | For a position with a stop, when a strategy enters or adds to it: sizes it so that falling from the last close to the stop loses at most this much of equity. A stop 5% below the close and a limit of 1% allow at most 20% of equity. It never sells what is already held to meet it |
| `max_open_positions` | Positions already held keep their place. New ones fill the free places, the largest first; the rest are not entered. A position the strategy is selling frees its place |
| `max_position_size` | Caps each instrument, at every close, including what is already held. When several strategies hold one instrument, each one's share shrinks by the same proportion |

Two more rules are measured on the whole account, at every close, before that close's decision:

| Rule | What the gate does |
|---|---|
| `daily_loss_limit` | If equity fell at least this much since the previous close, nothing is entered or added to at this close: every target above what is held comes down to the holding. Sales and reductions still go through. The next close starts fresh |
| `drawdown_kill` | If equity is at least this much below its highest close so far, **trading halts**: from that close on, no order of any kind is sent. What is held stays held, and a stop already resting at the broker can still sell. Nothing in a run lifts the halt, not even a new high |

Equity here is the whole account: cash plus positions at the latest close, after every fee.

**What a halted backtest does.** It runs on to its last day, holding whatever it held at the halt, marked at each close, with dividends credited. That is what your paper or live account would do if you never restarted it; the backtest cannot know when you would. So the result after a halt is the result of *not trading*, not of the strategy: read it that way. Its metrics still cover the whole range, so it stays comparable with the benchmark and with other runs.

The backtest's summary says which profile ran, how often the gate cut something, and what the account rules did:

```text
  Risk profile:  default; the risk gate shrank 10,909 contributions and blocked 0 entries
  Account rules: daily loss limit hit after 3 sessions; HALTED by the drawdown kill on 2020-03-18, 15.11% below the peak of 21817.50 USD; no order after that
```

The record (`run.json`) has the profile's values under `risk`, the counts by rule under `outcome.risk_adjustments`, and the account rules under `outcome.account_rules`: how many closes hit the daily loss limit, and the halt (`at`, `peak`, `equity`, `drawdown`, `limit`) or `null`. The report shows the counts under **What ran**; a halt also gets a warning at the top and a dashed line marked "halted" on the equity and drawdown charts.

### Expect smaller numbers under `default`

`default` caps every position at 20% of equity, so a strategy that wants to be fully invested in one fund holds a fifth of the account and leaves the rest in cash, which earns nothing in the simulator. On Yahoo data from 2005 to 2023, with USD 10,000:

| | No limits (as recorded before Phase 2) | `default`, position rules only (PR 2) | `default`, account rules too (PR 4) |
|---|---|---|---|
| Buy-and-hold SPY | 52,168 USD; max drawdown 53% | 14,568 USD; max drawdown 13% | unchanged |
| Trend rotation | 30,049 USD; max drawdown 30% | 23,464 USD; max drawdown 15% | 25,915 USD; max drawdown 20%; **halted 2020-03-18** |
| Mean reversion | 12,735 USD; max drawdown 12% | 10,650 USD; max drawdown 6% | unchanged |

The Sharpe ratios barely move under the position rules: the same funds, held smaller. Three things to keep in mind:

- **A halt can flatter or hurt a result, by luck.** The rotation fell 15.11% in March 2020 and halted. From then on it held the three funds it had that day, untouched, to the end of 2023. They recovered, so it ended higher than when it kept trading, but its worst fall grew from 15% to 20% (in 2022, with nothing to take it out of those funds). Neither number says anything about the strategy after March 2020.
- **Compare like with like.** A strategy under `default` against SPY held at 100% is not a fair test of the strategy. Run both under the same profile, or compare profiles side by side (below).
- **Small accounts may hold nothing.** With USD 1,000, 20% is about USD 200, less than one share of SPY, so buy-and-hold never buys. Run `tyche capital` to see where your account size stands.

Records written before this change have no `risk` section; their report says they ran before the risk gate.

## Comparing profiles side by side

`tyche compare-profiles` runs your configured strategies once under each risk profile, over the same days, with everything else the same ([ADR-0036](../adr/0036-risk-profiles-side-by-side.md)):

```bash
uv run tyche compare-profiles --from 2005-01-03                      # every profile in config/risk/
uv run tyche compare-profiles --from 2005-01-03 --risk-profile default --risk-profile stage-2
```

From the console: **Research**, **Profiles** ([the console](11-the-console.md)). To see every profile beside the guardrails without running anything: **Config**, **Risk**.

It prints one line per profile as it finishes, then where the record and the report are:

```text
Comparing 4 risk profiles: default, stage-1, stage-2, stage-3
  default: CAGR 5.14%, Sharpe 0.60, max drawdown 20.36%; daily loss limit hit after 3 sessions; HALTED by the drawdown kill on 2020-03-18, 15.11% below the peak of 21817.50 USD; no order after that
  stage-1: CAGR 2.71%, Sharpe 0.42, max drawdown 12.43%; daily loss limit hit after 1 session; drawdown kill never hit
  ...
```

Everything goes to `reports/profiles/<id>/`: `profiles.json`, each profile's full backtest record under `runs/<profile>/`, and `report.html`. The report shows every profile against the benchmark in one table, their equity and drawdown on one chart each with every halt marked, and what each profile's limits did: gate cuts, daily loss triggers, and when the drawdown kill halted it, with how much of the range was still to run.

Three things it deliberately does not do:

- **It names no best profile.** Choose a profile for the account you will trade and the losses you can sit through, not for the best number in the table. Choosing on these results is a selection, just like picking the best of a sweep, and the more profiles you compare, the better the best one looks by chance.
- **It adds no trials.** Every profile runs your strategies' configured parameters, which are already counted ([ADR-0030](../adr/0030-parameter-sweeps-trial-count-and-deflated-sharpe.md)), so nothing corrects for the selection either. The report says so at the top.
- **It does not use the money caps.** Like every research backtest it starts from `starting_cash`. To see a profile at one of your live stages, set `starting_cash` in `config/tyche.toml` to that stage's amount for the comparison (it is part of the config hash, so set it back after), and run `tyche capital` for what whole shares and minimum commissions cost there.

**A profile only ever lowers what a strategy asks for.** It never scales a strategy up to fill its slots. The example rotation asks for a third of the account in each of three funds, so under a one-position profile it holds one fund at a third and keeps the rest in cash. To use a one-position profile fully, the strategy has to ask for one position (for the rotation, `holdings = 1`, which is a new set of parameters and so a new trial).

## Profiles for a small account

`default`'s five positions of 20% cannot trade a small account: at about USD 700, a 20% slot is about USD 140, less than one share of SPY, QQQ, GLD or IWM ([ADR-0031](../adr/0031-minimum-viable-capital.md)). Use one profile per live stage, tightening as the account grows ([ADR-0036](../adr/0036-risk-profiles-side-by-side.md)). Tyche does not ship them: create them in your own workspace, beside `default`.

| File | `max_open_positions` | `max_position_size` | For |
|---|---|---|---|
| `config/risk/stage-1.toml` | `1` | `"1.0"` | The first stage: one position, as much of the account as it needs |
| `config/risk/stage-2.toml` | `2` | `"0.50"` | The second stage |
| `config/risk/stage-3.toml` | `4` | `"0.25"` | The third stage |

Each keeps `default`'s `risk_per_trade = "0.01"`, `daily_loss_limit = "0.03"` and `drawdown_kill = "0.15"`. The quickest way is to copy `default.toml` and change the two lines.

**Each needs room in your guardrails.** A profile may not exceed `config/guardrails.toml`, so while you trade at stage 1, `max_position_size` there must be at least `"1.0"`, and at stage 2 at least `"0.50"`. `max_open_positions` there must be at least the profile's. Lower the ceiling again as you move to the next stage: the guardrails are the hard limit, and they should be no looser than the stage you are in. `tyche config check` checks every profile against them, and refuses to start if one breaks a limit.

**Switch profile when you move stage**, by hand. Paper and live will run under the profile you choose; backtests take `--risk-profile`.

What these profiles did on real data (Yahoo, 2005 to 2023, USD 10,000, the example rotation alone):

| | CAGR | Max drawdown | Drawdown kill |
|---|---|---|---|
| `default` | 5.14% | 20.36% | halted 2020-03-18, 20% of the range left |
| `stage-1` | 2.71% | 12.43% | never (a third invested: see above) |
| `stage-2` | 4.59% | 32.81% | halted 2006-06-13, 92% of the range left |
| `stage-3` | 4.15% | 35.79% | halted 2006-06-13, 92% of the range left |

The halted profiles spent most of these years holding what they had in June 2006, so their figures say little about the strategy. With fewer, larger positions, a 15% fall from the peak comes sooner. Whether 15% is the right drawdown kill for a concentrated profile is part of choosing the profile.

## Your config hash

The config hash covers the guardrails and the **active** profile only. Adding or editing a profile you do not use leaves it unchanged; choosing another profile changes it.

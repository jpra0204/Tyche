# Risk profiles and guardrails

This page explains the three files that hold Tyche's risk limits, how to make a new risk profile, how to check them, and what they do to a backtest. The decisions behind them are in [ADR-0032](../adr/0032-risk-limits-in-three-layers.md) and [ADR-0033](../adr/0033-risk-gate-position-rules.md).

> **What works today.** Tyche reads and checks these files every time it starts, and refuses to start if one breaks a limit. **The risk gate applies the position rules** (risk per trade, max open positions, max position size) to every backtest. Not yet applied: the order check against the guardrails' money caps (Phase 2, PR 3), the daily loss limit and the drawdown kill switch (PR 4). This page grows with each.

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
                  (applied to trades: risk per trade, positions and position size; the daily loss limit, the drawdown kill and the money caps come later in Phase 2)
```

A breach stops Tyche, naming the file, the key, its value and the limit:

```text
Error: config/risk/safecash.toml: a risk profile may not exceed the guardrails (config/guardrails.toml)
  max_position_size = 0.30 is above max_position_size = 0.25
```

Fix the value, or the limit above it if you meant to change that, and check again.

## What a profile does to a backtest

Every backtest command runs under a risk profile: `tyche backtest`, `tyche walk-forward`, `tyche sweep` and `tyche capital` all take `--risk-profile <name>`, and use `default` without it.

```bash
uv run tyche backtest --from 2005-01-03 --risk-profile safecash
```

The risk gate sits between what the strategies want and what is traded. It only ever trades **less** than the strategies asked for:

| Rule | What the gate does |
|---|---|
| `risk_per_trade` | For a position with a stop, when a strategy enters or adds to it: sizes it so that falling from the last close to the stop loses at most this much of equity. A stop 5% below the close and a limit of 1% allow at most 20% of equity. It never sells what is already held to meet it |
| `max_open_positions` | Positions already held keep their place. New ones fill the free places, the largest first; the rest are not entered. A position the strategy is selling frees its place |
| `max_position_size` | Caps each instrument, at every close, including what is already held. When several strategies hold one instrument, each one's share shrinks by the same proportion |

The backtest's summary says which profile ran and how often the gate cut something:

```text
  Risk profile:  default; the risk gate shrank 4,781 contributions and blocked 0 entries
```

The record (`run.json`) has the profile's values under `risk`, and the counts by rule under `outcome.risk_adjustments`; the report shows both under **What ran**.

### Expect smaller numbers under `default`

`default` caps every position at 20% of equity, so a strategy that wants to be fully invested in one fund holds a fifth of the account and leaves the rest in cash, which earns nothing in the simulator. On Yahoo data from 2005 to 2023, with USD 10,000:

| | No limits (as recorded before Phase 2) | `default` |
|---|---|---|
| Buy-and-hold SPY | 52,168 USD; max drawdown 53% | 14,568 USD; max drawdown 13% |
| Trend rotation | 30,049 USD; max drawdown 30% | 23,464 USD; max drawdown 15% |
| Mean reversion | 12,735 USD; max drawdown 12% | 10,650 USD; max drawdown 6% |

The Sharpe ratios barely move: the same funds, held smaller. Two things to keep in mind:

- **Compare like with like.** A strategy under `default` against SPY held at 100% is not a fair test of the strategy. Run both under the same profile; comparing profiles side by side arrives in Phase 2, PR 5.
- **Small accounts may hold nothing.** With USD 1,000, 20% is about USD 200, less than one share of SPY, so buy-and-hold never buys. Run `tyche capital` to see where your account size stands.

Records written before this change have no `risk` section; their report says they ran before the risk gate.

## Your config hash

The config hash covers the guardrails and the **active** profile only. Adding or editing a profile you do not use leaves it unchanged; choosing another profile changes it.

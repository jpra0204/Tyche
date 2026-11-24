# User guide

Step-by-step instructions for Pablo as the person *using* Tyche. Each page is written in the phase that builds the feature, so that every step in it has actually been run.

## Available now

| Page | What it covers |
|---|---|
| [Installation and your workspace](01-installation.md) | Installing Tyche, creating your private workspace, checking its configuration |
| [Fetching market data](02-fetching-market-data.md) | Downloading prices, dividends and splits from Yahoo Finance, and reading the data issues |
| [Running a backtest](03-running-a-backtest.md) | The holdout, the instruments a backtest replays, the benchmark, running `tyche backtest`, its metrics, its record and its report |
| [Walk-forward](04-walk-forward.md) | In-sample and out-of-sample results: running `tyche walk-forward`, how the test windows are joined, its record and its report |
| [Parameter sweeps](05-parameter-sweeps.md) | Writing a sweep file, running `tyche sweep`, the trial count and the deflated Sharpe ratio, the warnings, and sweeps inside a walk-forward |
| [Minimum viable capital](06-minimum-viable-capital.md) | Running `tyche capital`: the account size at which each strategy stops losing to its size, Fixed against Tiered, and what a position costs at today's prices |
| [Troubleshooting](07-troubleshooting.md) | First checks, upgrading a workspace created by an older Tyche, messages any command can print, and common questions |
| [Risk profiles and guardrails](08-risk-profiles.md) | The three layers of risk limits, making a new profile, checking them, what the risk gate does to a backtest (`--risk-profile`), comparing profiles side by side (`tyche compare-profiles`), and one profile per live stage for a small account |
| [Discord alerts, secrets and logs](09-discord-alerts-and-logs.md) | Setting up the Discord webhook and checking it (`tyche notify test`), the `.env` file, which alerts exist and when they are sent, and the daily log files |

## Planned

| Page | What it will cover | Written in |
|---|---|---|
| `10-first-time-setup.md` | IBKR paper account, IB Gateway, choosing a market profile and a risk profile | Phase 2 |
| `11-daily-and-weekly-routine.md` | What Tyche does by itself and what you check | Phase 2 |
| `12-reading-discord-reports.md` | The daily summary, and each alert in detail | Phase 2 |
| `13-kill-switch.md` | Stopping new orders and flattening positions | Phase 2 |
| `14-weekly-review.md` | Running the review and approving or rejecting proposals | Phase 3 |
| `15-promoting-a-strategy.md` | Taking a strategy from paper to live | Phase 3 |

[Risk profiles and guardrails](08-risk-profiles.md) grows through Phase 2: switching the paper profile comes later.

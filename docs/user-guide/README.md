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

## Planned

| Page | What it will cover | Written in |
|---|---|---|
| `06-first-time-setup.md` | IBKR paper account, IB Gateway, Discord webhook, `.env`, choosing a market profile and a risk profile | Phase 2 |
| `07-daily-and-weekly-routine.md` | What Tyche does by itself and what you check | Phase 2 |
| `08-reading-discord-reports.md` | The daily summary and each kind of alert | Phase 2 |
| `09-risk-profiles.md` | Creating, comparing and switching risk profiles | Phase 2 |
| `10-kill-switch.md` | Stopping new orders and flattening positions | Phase 2 |
| `11-weekly-review.md` | Running the review and approving or rejecting proposals | Phase 3 |
| `12-promoting-a-strategy.md` | Taking a strategy from paper to live | Phase 3 |
| `13-troubleshooting.md` | Common problems and questions; grows with every phase | Phase 1 onward |

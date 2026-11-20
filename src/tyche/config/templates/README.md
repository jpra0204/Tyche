# Tyche workspace

This folder is your private Tyche workspace: your configuration and, as Tyche grows, your research notes, proposals, reports, data and trading state. The Tyche code lives in a separate, public repository; nothing in this folder belongs there.

Keep this folder a **private** git repository. Never push it anywhere public.

| Path | Holds | Committed |
|---|---|---|
| `config/tyche.toml` | Workspace settings: the active market profile, the strategies to run with their budgets, and the backtest settings with the holdout | Yes |
| `config/markets/` | One file per market profile: the instruments followed and the rules for trading them | Yes |
| `config/costs/` | Trading costs and settlement for each market profile, with the date they were checked | Yes |
| `config/strategies/` | One file per strategy: which built-in plugin and its parameters. A strategy runs only with a budget in `config/tyche.toml`; the two examples ship without one | Yes |
| `reports/backtests/` | One folder per backtest run: what ran, the equity at every close, every fill, the metrics and `report.html` | Yes |
| `reports/walk_forward/` | One folder per walk-forward: what ran, the test windows joined, `report.html`, and each training and test window's backtest record | Yes |
| `data/` | Market data fetched from Yahoo Finance, for personal use only | **Never** |
| `.env` | Secrets: Discord webhook, broker connection | **Never** |

More folders appear as the features that use them are built.

Check that the configuration is valid at any time:

```bash
tyche config check
```

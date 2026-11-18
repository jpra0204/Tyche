# Tyche workspace

This folder is your private Tyche workspace: your configuration and, as Tyche grows, your research notes, proposals, reports, data and trading state. The Tyche code lives in a separate, public repository; nothing in this folder belongs there.

Keep this folder a **private** git repository. Never push it anywhere public.

| Path | Holds | Committed |
|---|---|---|
| `config/tyche.toml` | Workspace settings: the active market profile, and the strategies to run with their budgets | Yes |
| `config/markets/` | One file per market profile | Yes |
| `config/costs/` | Trading costs and settlement for each market profile, with the date they were checked | Yes |
| `config/strategies/` | One file per strategy you run: which built-in plugin and its parameters. Budgets are in `config/tyche.toml` | Yes |
| `.env` | Secrets: Discord webhook, broker connection | **Never** |

More folders appear as the features that use them are built.

Check that the configuration is valid at any time:

```bash
tyche config check
```

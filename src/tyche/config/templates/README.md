# Tyche workspace

This folder is your private Tyche workspace: your configuration and, as Tyche grows, your research notes, proposals, reports, data and trading state. The Tyche code lives in a separate, public repository; nothing in this folder belongs there.

Keep this folder a **private** git repository. Never push it anywhere public.

| Path | Holds | Committed |
|---|---|---|
| `config/tyche.toml` | Workspace settings, including the active market profile | Yes |
| `config/markets/` | One file per market profile | Yes |
| `.env` | Secrets: Discord webhook, broker connection | **Never** |

More folders appear as the features that use them are built.

Check that the configuration is valid at any time:

```bash
tyche config check
```

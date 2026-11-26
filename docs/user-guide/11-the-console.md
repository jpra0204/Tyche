# The console

A page in your browser to see your workspace and, as it grows, to run Tyche from it. It runs on your Mac only. Design: [ADR-0046](../adr/0046-a-local-web-console.md).

> **Today (console PR U1)** it has one page, **Status**, and only reads. Running commands from it comes in U2 (data and backtests) and U3 (the paper run). Until then, run them in the terminal.

## Open it

1. **Build the page once**, and again after each update of Tyche:

   ```bash
   make ui
   ```

   It installs the page's packages and writes `ui/dist`. Expect `✓ built in …` at the end.

2. **Start the console:**

   ```bash
   uv run tyche ui
   ```

   It prints an address like `http://127.0.0.1:8765/#token=…` and opens it in your browser. Leave the terminal open: the console runs until you press **Ctrl+C** there.

   Options: `--home <folder>` for another workspace, `--port <n>` if 8765 is taken, `--no-browser` to open the address yourself.

## The Status page

| Card | Shows |
|---|---|
| **Trading** | Whether anything stops trading: the kill switch (with its reason), the drawdown halt, a reconciliation halt and its differences. **Trading allowed** in green, or **Stopped** in red |
| **Configuration** | Whether `tyche config check` passes, and if not, why; the market profile, the risk profile chosen at the top of the page, the money caps, the strategies and their budgets, the config hash; whether the Discord webhook and the IB Gateway connection are set in `.env` (never their values) |
| **Account** | Tyche's account as the last paper run saved it: cash settled and still to settle, positions at what they cost, orders still working at IBKR. Empty until your first `tyche paper run` |

**Risk profile** at the top chooses which profile the configuration is checked against, as `tyche config check --risk-profile` does. It changes nothing in your workspace. **Refresh** reads everything again; the page also refreshes when you come back to its tab.

## The key in the address

The part after `#token=` is a new random key made at every launch. The console answers only a page that has it, so a website you visit cannot drive it. It never leaves your machine, and the page removes it from the address bar once it has read it.

- **Do not share the address.** Anyone with it, on your machine, can use the console while it runs.
- An old address stops working when the console restarts: open the new one it prints.
- A tab opened without the key shows *Open the console from its own address*.

## If it did not work

| You see | Do |
|---|---|
| `the console's page is not built …; run make ui` | Run `make ui`, then `uv run tyche ui` again |
| `[Errno 48] Address already in use` | Another console (or program) uses port 8765. Stop it, or add `--port 8766` |
| *Open the console from its own address* | Open the address printed in the terminal, with its `#token=…` |
| *The console's key does not match this launch* | The console restarted. Open the new address it printed |
| `npm: command not found` during `make ui` | Install Node 22 or later (nodejs.org, or Homebrew `brew install node@22`) |

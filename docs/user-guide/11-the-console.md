# The console

A page in your browser to see your workspace and, as it grows, to run Tyche from it. It runs on your Mac only. Design: [ADR-0046](../adr/0046-a-local-web-console.md).

> **Today (console PR U2)** it has three pages: **Status** reads; **Data** and **Backtests** run `tyche data fetch` and `tyche backtest` for you and show their reports. The paper run, the kill switch and resume come in U3; walk-forward, sweeps, capital and profile comparison in U4. Until then, run those in the terminal.

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

## Running a command from the page

**Data** and **Backtests** run the same `tyche` command you would type, in the console's workspace, and show what it prints as it prints it. Anything the command refuses in the terminal it refuses here, with the same message (in red).

- **One run at a time.** While one runs, its command shows at the top of every page and the buttons that start runs are greyed out. Leaving the page does not stop it.
- **The last run stays on the page** until the next one starts, or the console restarts. What it wrote (the cache, `reports/`) stays in the workspace as usual.
- **Stopping a run:** there is no stop button. Pressing **Ctrl+C** in the console's terminal stops the console and the run with it, as Ctrl+C stops a command in the terminal.

### The Data page

Fetches daily bars, dividends and splits from Yahoo Finance into the cache, like `tyche data fetch`.

| Choice | Runs |
|---|---|
| **Everything Tyche follows** | `tyche data fetch --all`: the market profile's candidates and its benchmark, listed on the page. What a backtest needs |
| **Chosen symbols** with an **Exchange** and **Asset class** | `tyche data fetch SPY QQQ --exchange ARCX` |
| **From** / **To** | `--from` / `--to`. Empty: from 2000-01-01 to today |

Only sessions not already cached are downloaded. Yahoo's data is for personal use only.

### The Backtests page

**Run a backtest:** choose **From** (required), **To** (empty means the day before the holdout) and the **Risk profile**, then **Backtest**. It runs `tyche backtest --from … --to … --risk-profile …` on the cache only, so fetch first. A range that reaches the holdout is refused, as in the terminal.

Every run is recorded. Running many and keeping the best one is overfitting, not progress.

**Recorded backtests** lists every backtest in `reports/backtests/`, newest first: its range, risk profile, final equity, return, the benchmark's return (hover for which), the deepest drawdown and how it ended (**Completed**, **Drawdown kill**, **Failed**, or **Unreadable** if its record cannot be read; hover for why).

- **Report** opens its `report.html` inside the console. **Backtests** at the top goes back.
- **Write report** appears when a record has no report yet; it runs `tyche report <run id>`.

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
| *run N (…) is still running; wait for it to end* | A run is going (its command is at the top of the page). Wait for it, or stop the console with Ctrl+C |
| A run shows `Error: … Fetch it first` | The cache lacks what the backtest needs: run the fetch it names on the **Data** page |
| A new page or button is missing after an update | Run `make ui` again, then restart the console |

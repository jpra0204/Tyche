# The console

A page in your browser to see your workspace and, as it grows, to run Tyche from it. It runs on your Mac only. Design: [ADR-0046](../adr/0046-a-local-web-console.md).

> **Today (console PR U5)** it has six pages: **Status** and **Config** read; **Data**, **Backtests** and **Research** run `tyche data fetch`, `tyche backtest`, `tyche walk-forward`, `tyche sweep`, `tyche capital` and `tyche compare-profiles` and show their reports; **Paper** runs the paper cycle, the kill switch and resume. The configuration is edited in its files, by hand; editing from the page would come later, with its own decision.

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

### The Research page

A tab for each study beyond one backtest. Each tab has a form that runs the command, the run's output, and every record of that kind in the workspace, newest first, with a line saying what it found and a **Report** (or **Write report**) button. Coming back from a report returns to the same tab.

| Tab | Runs | The form |
|---|---|---|
| **Walk-forward** | `tyche walk-forward` ([walk-forward](04-walk-forward.md)) | From, To, risk profile, training and test years, **Rolling**, and an optional **sweep on each training window** |
| **Sweep** | `tyche sweep <name>` ([sweeps](05-parameter-sweeps.md)) | The sweep (a file in `config/sweeps/`), From, To, risk profile |
| **Capital** | `tyche capital` ([minimum viable capital](06-minimum-viable-capital.md)) | From, To, risk profile; amounts, reference, tolerance and positions, each showing its default. Empty keeps the default |
| **Profiles** | `tyche compare-profiles` ([comparing profiles](08-risk-profiles.md)) | From, To, and every profile or the ones you choose |

The same honesty applies as in the terminal: every sweep's trials count against every later Sharpe ratio of its plugin, a sweep's pick is in-sample, and a profile comparison names no best profile. The forms say so under their fields.

### The Paper page

Everything about the IBKR **paper** account in one place. Live trading is never run from the console.

| Card | Shows, or does |
|---|---|
| **Paper cycle** | **Run the paper cycle…** runs `tyche paper run --risk-profile <the one chosen>`, after a dialog that says what it will do: connect to IB Gateway, reconcile, and, if a session has closed, **send orders** for the next open. Greyed out until the IB Gateway connection is set in `.env` and the configuration passes its check |
| **Trading** | The kill switch and the halts, as on Status. **Kill switch…** asks for a reason, and with **Also flatten** a second tick (*I want every holding sold*), then runs `tyche kill`. **Resume…** (only when something stops trading) lists exactly what it lifts, asks for a reason, then runs `tyche resume` |
| **Account** | As the last paper run saved it |
| **Reconciliation** | The last cycle's two checks against IBKR: at the start, and after the decision if one ran. Each is a **match**, **corrected** or a **mismatch**, with its differences, fills inferred on a day no run read, orders that ended unfilled, and cash, Tyche's against IBKR's |
| **Alerts** | The latest 50, newest first, from the logs: what each said, and whether Discord got it (**sent**, **not sent** with why, or **no channel** when `DISCORD_WEBHOOK_URL` is empty) |

The dialogs are the same questions the commands ask in the terminal; the page answers them for the command (`--yes`) only after you have.

**One run at a time applies here too.** While a backtest or a fetch runs, **Kill switch…** waits for it. In a hurry, the terminal always works: `uv run tyche kill --reason "..."`. The same rule keeps you from engaging or resuming in the middle of a paper cycle started from the page, which the runbooks ask you never to do.

### The Config page

Your configuration as Tyche reads it, **read-only**: edit the files in the workspace's `config/` folder, then press **Refresh**.

| Tab | Shows |
|---|---|
| **Check** | Whether `tyche config check` passes under `default`, and if not, its message; the config hash; a warning if other users can read `.env` |
| **Risk** | Each profile in `config/risk/` beside the guardrails, limit by limit, each checked as the active one (as `--risk-profile` would); a profile that does not pass shows why. The money caps for paper and live |
| **Strategies and sweeps** | Each strategy's plugin, file, budget, parameters and own limits, and the cash left over; each sweep's values and how many combinations it runs, or why it cannot run |
| **Market** | The market profile in short: currencies, calendars, candidates, benchmark, rebalance band, price buffer; the backtests' starting cash, the holdout date, when costs were last checked |
| **Files as loaded** | Every setting of every file Tyche loaded, exactly as hashed: what a run record stores |

`.env` is never shown, only whether other users can read it; the Status page says which secrets are set.

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

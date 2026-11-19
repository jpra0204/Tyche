# Installation and your workspace

This page gets Tyche onto your Mac and creates your private workspace. It takes about ten minutes. Nothing here connects to a broker or spends money.

## What you need

- macOS with [Homebrew](https://brew.sh).
- [uv](https://docs.astral.sh/uv/), which installs the right Python version for you. Install it with:

  ```bash
  brew install uv
  ```

- git, which comes with the Xcode command-line tools.

## 1. Get the code

```bash
git clone https://github.com/jpra0204/Tyche.git
cd Tyche
make install
```

`make install` creates a virtual environment with the pinned Python version (3.14) and the exact library versions from `uv.lock`.

Check it worked:

```bash
uv run tyche --version
```

You should see `tyche` and a version number.

## 2. Create your workspace

Your workspace is a separate, private folder for everything that is yours: configuration now, and later your data, reports, proposals and trading state. The code repository is public, so none of this goes in it.

```bash
uv run tyche init
```

This creates `~/tyche-workspace` with:

| File | What it is |
|---|---|
| `config/tyche.toml` | Workspace settings, including the active market profile |
| `config/markets/US.toml` | The `US` market profile, including its universe rules: which instruments may be traded (asset classes, a minimum price, a minimum average dollar volume, and how long data problems keep an instrument out) |
| `config/costs/US.toml` | What trading costs under the `US` profile (IBKR Pro Fixed), slippage and settlement, with the date the rates were checked |
| `.env` | Where secrets will go in Phase 2. Empty for now, and readable only by you |
| `.gitignore` | Keeps `.env`, market data, state and logs out of git |
| `README.md` | A short description of the folder |

`tyche init` refuses to:

- overwrite a folder that already has something in it;
- create the workspace inside `~/Public`, `~/Desktop` or `~/Documents`, or inside any git repository, including the Tyche code itself.

### Using a different folder

```bash
uv run tyche init --home /path/to/folder
```

Then tell Tyche where it is, in your shell profile (for example `~/.zshrc`):

```bash
export TYCHE_HOME=/path/to/folder
```

Tyche looks for the workspace in this order: the `--home` option, then `TYCHE_HOME`, then `~/tyche-workspace`.

## 3. Make the workspace a private git repository

Your configuration should be versioned, so you can see what changed and when.

```bash
cd ~/tyche-workspace
git init
git add .
git commit -m "Create Tyche workspace"
```

Check that `.env` was not committed:

```bash
git ls-files
```

The list should not contain `.env`.

If you also keep it on GitHub, create the repository as **private**. Never make it public.

## 4. Check the configuration

From the Tyche code folder:

```bash
uv run tyche config check
```

You should see:

```text
Configuration is valid: /Users/<you>/tyche-workspace
  Market profile: US
  Costs checked:  2026-11-17
  Execution:      rebalance band 0.10, price buffer 0.02
  Strategies:
    buy_and_hold (buy_and_hold), budget 1.0
  Config hash:    sha256:…
```

`Costs checked` is the date the commission and fee rates in `config/costs/US.toml` were last compared with IBKR's published prices. Check them again before paper trading and before going live; [the facts page](../developer-guide/ibkr-canada-costs-and-settlement.md) lists the sources.

`Execution` shows two choices in `config/markets/US.toml` that change every result, so reports will state them too ([ADR-0023](../adr/0023-execution-sleeves-stops-and-cash.md)):

- **Rebalance band**: a holding is resized only when it has drifted more than this fraction from its target (0.10 is 10%). Each trade pays at least the USD 1.00 minimum commission, so small drifts are cheaper to leave alone. Buying and selling a whole position always happens.
- **Price buffer**: purchases are sized at the close but fill at the next open, so Tyche leaves this much room (0.02 is 2%) for the open to be higher. A purchase the cash cannot pay for at the open is rejected whole. A fully invested strategy therefore holds about 2% in cash.

The config hash is a fingerprint of every setting. Tyche will print it in every backtest report and run log, so you can always tell which configuration produced a result. Editing a comment or reordering keys does not change it; changing any value does.

If something is wrong, the message names the file and the setting:

```text
Error: config/tyche.toml: 1 invalid setting(s)
  risk_profle: Extra inputs are not permitted
```

Unknown settings are always an error, so a misspelled key cannot be silently ignored.

## 5. Choose your strategies

A new workspace runs one strategy: the buy-and-hold benchmark on SPY, with the whole account. Two files say so.

`config/tyche.toml` lists each strategy with its **budget**, the fraction of the account it may use:

```toml
[strategies]
buy_and_hold = "1.0"
```

Budgets are above 0 and at most 1, and add up to at most 1; whatever is left stays as cash, and `tyche config check` prints it. Write them as strings (`"0.5"`, not `0.5`) so they stay exact.

Each name has its own file, `config/strategies/<name>.toml`, saying which built-in strategy to run and with what parameters:

```toml
plugin = "buy_and_hold"

[parameters]
symbol = "SPY"
exchange = "ARCX"
asset_class = "etf"
```

To run a second strategy, add a line under `[strategies]` and a file with the same name. `tyche config check` builds every strategy, so a misspelled parameter, an unknown plugin or an exchange outside the market profile is reported with the file and the key:

```text
Error: config/strategies/buy_and_hold.toml: 1 invalid parameter(s)
  parameters.exchange: Field required
```

Only Tyche's built-in strategies can be named for now. How the budgets combine is explained in [backtesting internals](../developer-guide/backtesting-internals.md#5-how-strategies-share-the-account).

**A workspace created before PR 13** has no `[strategies]` table, and `tyche config check` reports `strategies: Field required`. Add the table above to `config/tyche.toml` and copy `config/strategies/buy_and_hold.toml` from a new workspace (`tyche init --home <scratch-folder>`).

## Troubleshooting

| Message | What to do |
|---|---|
| `config/tyche.toml is missing; is … a Tyche workspace?` | Tyche is looking in the wrong folder. Check `TYCHE_HOME`, or run `tyche init` if you have no workspace yet. |
| `TYCHE_HOME is set but empty` | Unset it (`unset TYCHE_HOME`) or give it a path. |
| `… is not empty; tyche init only creates a new workspace` | You already have a workspace there. Use `tyche config check` instead. |
| `… is inside ~/Documents, which macOS can sync to iCloud` | Choose a folder outside `~/Public`, `~/Desktop` and `~/Documents`. |
| `… selects market profile 'CA', but config/markets/CA.toml does not exist` | Only `US` exists for now. `CA` and `CA+US` arrive in Phase 4. |
| `config/costs/US.toml is missing: every market profile needs a costs file` | Your workspace was created before costs existed. Run `uv run tyche init --home <scratch-folder>` and copy its `config/costs/US.toml` into your workspace. |
| `config/markets/US.toml: … universe: Field required` | Your workspace was created before the universe rules existed. Run `uv run tyche init --home <scratch-folder>` and copy the `[universe]` table from its `config/markets/US.toml` into yours. |
| `config/markets/US.toml: … execution: Field required` | Your workspace was created before PR 14. Copy the `[execution]` table, with its comments, from the `config/markets/US.toml` of a new workspace (`uv run tyche init --home <scratch-folder>`) into yours. |
| `config/tyche.toml: … strategies: Field required` | Your workspace was created before strategies were configured. See [Choose your strategies](#5-choose-your-strategies) for the table to add and the file to copy. |
| `write decimals as strings, such as "0.005", so they stay exact` | Put quotes around the number in the costs, market profile or `[strategies]` table: `per_share = "0.005"`, not `per_share = 0.005`. |

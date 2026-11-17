# Fetching market data

Tyche downloads daily prices, dividends and splits from Yahoo Finance and keeps them in your workspace, so backtests run without the internet and the same data is used every time.

You need a workspace first: see [Installation and your workspace](01-installation.md).

## Before you start: Yahoo's terms

Yahoo Finance data is free, but **for personal use only**. The yfinance library Tyche uses is not affiliated with Yahoo. In practice:

- use the data for your own research and trading only;
- never share or publish it. Tyche keeps it in your workspace's `data/` folder, which `.gitignore` keeps out of git;
- expect Yahoo to change or limit access without notice. Tyche retries briefly and then reports the failure.

## Fetch

From the Tyche code folder:

```bash
uv run tyche data fetch SPY --exchange ARCX
```

| Part | Meaning |
|---|---|
| `SPY` | One or more symbols, as the exchange lists them. Share classes use a dot: `BRK.B`. |
| `--exchange` | Where the symbol is listed, as a market code: `ARCX` (NYSE Arca), `XNAS` (Nasdaq), `XNYS` (New York Stock Exchange), `BATS` (Cboe BZX), `XASE` (NYSE American). |
| `--asset-class` | `etf` (the default) or `stock`. |
| `--from` | First date, `YYYY-MM-DD`. Defaults to 2000-01-01. The earliest allowed is 1990-01-01. |
| `--to` | Last date. Defaults to today. |

Tyche does not check that the exchange you give is the one the symbol really trades on: Yahoo answers by symbol alone. If you are unsure, the exchange is shown on the fund's or company's own website. Full instrument lists come with the universe later in Phase 1.

Several symbols on the same exchange can be fetched at once:

```bash
uv run tyche data fetch QQQ AAPL --exchange XNAS --from 2015-01-01
```

## Reading the result

```text
SPY@ARCX: 124 bars, 2024-01-02 to 2024-06-28; 2 distributions; 0 splits
  fetched 2026-11-17 22:25 to 2026-11-17 22:25 UTC
```

- **bars**: one per trading session. Holidays and weekends are not missing; Tyche knows the exchange calendar.
- **distributions**: dividends (and, for some funds, capital-gain payments). Prices are **not** adjusted for them; backtests will credit them as cash.
- **splits**: prices before a split are already adjusted for it.
- **fetched**: when the data was downloaded. Yahoo revises history now and then, so reports will show this.

If something looked wrong, it is listed:

```text
  2 data issue(s):
    2008-10-10 suspect_move: close moved -55.0% from ...; check for a split or a bad price
    2024-01-17 missing_session: no bar for this session
```

| Issue | What it means | What to do |
|---|---|---|
| `missing_session` | The market was open, but Yahoo has no bar | Usually nothing; if it persists for recent days, fetch again later |
| `suspect_move` | A move of more than 50% in one session | Check the date against another source; often a missed split |
| `off_session`, `conflict`, `duplicate`, `invalid_bar`, `mixed_adjustment`, `wrong_series` | Bad rows were dropped, not cached | Nothing; they are reported so you know |

## Fetching again

Run the same command any time. Only sessions not already cached are downloaded, so a daily re-run is quick. If a symbol has had a new split since the last fetch, its whole history is downloaded again, because a split changes every earlier price.

To force a complete refetch of one symbol, delete its file under `data/bars/yfinance/1d/<exchange>/` and fetch again.

## When it fails

| Message | What to do |
|---|---|
| `Yahoo Finance does not know the symbol 'X'` | Check the spelling. Share classes use a dot (`BRK.B`). |
| `Yahoo Finance failed for 'X' after 3 attempts` | Yahoo is rate-limiting or unreachable. Wait a few minutes and try again. |
| `unknown exchange 'XTSE'` | Only US exchanges are supported for now. Toronto arrives in Phase 4. |
| `... is not part of market profile ...` | The exchange is outside your active market profile in `config/tyche.toml`. |

The command exits with code 1 if any symbol failed; the others are still fetched and cached.

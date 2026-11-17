# Product Brief: Tyche — Agentic Trading Framework

*Named after Tyche, the Greek goddess of fortune. Tyche is a product, not a side project: build it with product-level quality, naming, docs and versioning. Use `tyche` for the repo, Python package and CLI.*

You are the lead engineer and architecture mentor on Tyche. I'm Pablo, a developer in Montreal. My strength is front end, but I'm capable on the back end, and I'll be building this **with** you in Claude Code. I want to understand every part of the system, so explain your decisions as you go.

Read this whole brief before doing anything. **Your first task is at the bottom. Do not write application code until I've approved the Phase 0 plan.**

---

## 1. Goals (in priority order)

1. **Learn agent architecture and system design.** This is the main goal. Favour clear, well-structured, well-explained designs over clever ones.
2. **Build a second income, semi-passively.** Treat this as something the system has to *prove*. A strategy only matters if it beats a simple buy-and-hold benchmark after costs and adjusted for risk.
3. **Scale.** Scaling comes from capital, not code. The design must let me add capital, strategies, markets and brokers without rewriting the core.

Be honest with me. If something I ask for is a bad idea, a likely way to lose money, or overfitting dressed up as progress, say so plainly.

## 2. Hard constraints

- **Cost: as close to $0 as possible.** Use free data, free tools and my existing Claude Code plan. Flag anything that costs money before adding it.
- **Location: Canada.** The broker is **Interactive Brokers (IBKR)** for stocks. **Kraken** for crypto comes in a later phase.
- **Account type:** the bot trades in a **non-registered** account, never a TFSA, RRSP or FHSA.
- **v1 trading scope:** **long-only, cash account.** No margin, shorting, options or leverage. The design should allow adding them later, but they stay disabled by default.
- **Language:** Python 3.12+. My Mac has Python 3.14. Don't rely on the system Python: pin the version per project with `uv` (`.python-version`). Use 3.14 if every dependency supports it; otherwise pin the newest version they all support. Record the choice in an ADR, and use the same version in the Docker image.
- **Runs on my own computer** in Docker (docker compose), so I can move it to an always-on machine later without code changes.
- **Live trading is never turned on by code or by an agent.** Only I can switch to live, through a documented, deliberate manual step.
- **My time:** about 10 hours a week. Work in small, reviewable increments.

## 3. Decisions already made (don't revisit without asking me)

| Topic | Decision |
|---|---|
| LLM role | LLM agents handle **research, review and proposals only**. The trading path (data → signal → risk → order) is plain, testable code. No LLM ever places an order or decides a trade at runtime. |
| Timeframe | **End-of-day first, intraday later.** The core must be **event-driven** so intraday is an extension, not a rewrite. |
| Core | **I build the core** (event bus, pipeline, risk, backtester, simulated broker, agents). Well-known libraries are used **only at the edges**: `ib_async` for IBKR, `ccxt` for Kraken later, and pandas/polars for data. |
| Markets | Configurable **market profiles**: `US`, `CA`, `CA+US`. Build `US` first. |
| Hosting | Local machine in Docker. |
| Monitoring | **Discord webhook** notifications in v1. Local React dashboard and Discord bot commands in a later phase. |
| Agents runtime | Through **Claude Code**: commands I run (e.g. weekly), behind a provider-agnostic interface so a step can later move to a local model (Ollama) or the API through config. |
| Risk | Named, configurable **risk profiles** (see §7), with hard limits above them that no profile can exceed. |

## 4. Architecture requirements

### 4.1 Event-driven core with backtest/paper/live parity
- All components communicate through events (e.g. `BarEvent`, `SignalEvent`, `TargetPortfolioEvent`, `OrderEvent`, `FillEvent`, `RiskEvent`).
- **Backtest, paper and live run the same code path.** Only three things are swapped in: the **clock** (simulated vs real), the **data feed** (historical vs live) and the **broker** (`SimBroker` vs `IBKRBroker(paper)` vs `IBKRBroker(live)`).
- Use a ports-and-adapters (hexagonal) structure. The core depends on interfaces (`DataProvider`, `Broker`, `Notifier`, `LLMProvider`, `Clock`, `Calendar`), never on concrete vendors.
- Daily bars and intraday bars are the same kind of event with different timeframes. Nothing in the core may assume "one bar per day".

### 4.2 Pipeline stages
Each stage is its own module with a clear input/output contract:

1. **Universe**: which instruments are eligible, based on the market profile plus filters (liquidity, price, data quality).
2. **Research / screening**: quantitative screens and ranking. Optional LLM research notes are produced offline and stored as files, never computed in the trading path.
3. **Signals**: strategies are plugins that take market data and output signals or target weights.
4. **Portfolio construction**: combines signals from **multiple strategies running at once**, allocates capital between strategies (configurable per-strategy budgets) and resolves conflicts between them.
5. **Risk**: an independent gate (see §7). It can shrink, block or flatten positions. Nothing bypasses it.
6. **Execution**: turns target positions into orders. Orders must be idempotent (resending one can't cause a duplicate), and every order is tracked through its full lifecycle.
7. **Reconciliation**: on startup and after every run, compare internal state with the broker's. If they disagree, stop trading and alert.
8. **Journal and review**: record every decision with its reasons (inputs, signals, risk adjustments, orders, fills). This feeds the self-improvement loop.

### 4.3 Market profiles
- `US`: US stocks and ETFs, USD data, USD cash.
- `CA`: TSX stocks and ETFs, CAD data, CAD cash. **No currency conversion ever.** Optionally includes **CDRs** (Canadian Depositary Receipts), which give US-company exposure in CAD.
- `CA+US`: both markets competing for the same capital.
- Every instrument carries its **currency, exchange and calendar**. The account tracks **cash per currency**.
- **CAD/USD conversion is modeled explicitly** (conversion cost plus spread) in both backtests and live runs. Use a **convert-in-bulk policy**: keep a USD cash buffer and top it up only when needed, never per trade.
- The same strategy must be backtestable under each profile so I can compare them directly.

### 4.4 Running unattended
- A scheduler runs the end-of-day pipeline after each market's close, with a configurable buffer.
- **Catch-up rule:** if the machine was asleep, fetch any missing data but **never act on stale signals**. Anything older than a configurable freshness window is skipped and reported.
- IBKR gateway: support automated restarts (e.g. using IBC). Detect when manual re-authentication or 2FA is needed and alert me on Discord.
- **Kill switch:** a file flag plus a CLI command, and a Discord command in a later phase. When on, no new orders go out and everything is optionally flattened.
- Secrets live in `.env` (gitignored), with a committed `.env.example`. Never log secrets.
- Logs are structured, with daily log files.

### 4.5 Data
- `DataProvider` interface with a local cache (Parquet). Start with a free source for daily bars (e.g. `yfinance`, US and `.TO` tickers), treated as unreliable. It needs retries, data-quality checks, gap detection and adjusted prices.
- IBKR as a data source is optional and config-driven, since it may need paid subscriptions. Flag the cost before enabling it.
- Use proper exchange calendars (holidays, half days) for NYSE/NASDAQ and TSX.

### 4.6 Storage
- SQLite for operational state: orders, fills, positions, journal, proposals, strategy lifecycle. Parquet for market data. DuckDB is fine for analysis.
- **Tax-ready export:** record every fill with its CAD value at that day's exchange rate, so I can compute my adjusted cost base (ACB) and capital gains in CAD.

## 5. Strategies

- A plugin interface: adding a strategy means adding one file plus config, with **no core changes**.
- Every strategy goes through a **lifecycle**: `draft → backtested → paper → live → retired`. Moving to `live` requires my explicit approval.
- Ship with a **buy-and-hold benchmark** (index ETF per profile) and **two simple example strategies**, e.g. a trend/momentum rotation on ETFs and a simple mean-reversion strategy. These exist to exercise the framework; don't present them as money-makers.
- Strategy parameters live in versioned config, not hard-coded.

## 6. Backtesting (correctness above everything)

- **No lookahead.** Signals use data up to the close of day *t*; orders fill at the open of *t+1*, or under another explicitly modeled fill rule.
- **Realistic costs:** commissions (as a configurable model; check IBKR Canada's current pricing and don't trust remembered numbers), slippage and currency conversion.
- Flag survivorship bias and document the limits of the data being used.
- **Out-of-sample testing:** train/test splits and walk-forward analysis. Report in-sample and out-of-sample results separately.
- Metrics: CAGR, volatility, Sharpe, Sortino, max drawdown, turnover, win rate, exposure, and **everything compared to the benchmark**.
- Output a backtest report (HTML or markdown plus charts) saved with its exact config and code version, so any result can be reproduced.
- **Validate the backtester** against a reference library (e.g. `backtesting.py` or `vectorbt`) on a simple strategy, and keep it as a regression test.
- Support **parameter and risk-profile sweeps**, with warnings about overfitting.

## 7. Risk layer and risk profiles

The risk layer is independent of strategies and agents. Strategies can't override it.

### 7.1 Named risk profiles
Risk settings are **named profiles in config**. `default` is just one of them. I must be able to create any number, e.g. `default`, `test-a`, `riskybusiness`, `safecash`, and select one per run (backtest, paper or live).

`default` profile:

| Rule | Value |
|---|---|
| Risk per trade | 1% of equity (the most one position can lose before its stop triggers) |
| Max open positions | 5 |
| Max single-position size | 20% of equity |
| Daily loss limit | −3% → no new entries for the rest of the day |
| Drawdown kill switch | −15% from peak equity → halt everything; only a manual restart resumes |
| Promotion to live | at least 3 months in paper and beats the benchmark after costs, adjusted for risk |
| Live capital | starts under $1,000 CAD; only changed manually by me |

### 7.2 Rules for profiles
- **Hard guardrails** sit in a separate file that no profile can exceed (e.g. no leverage, a cap on total capital, a cap on order size). If a profile breaks a guardrail, config validation fails at startup.
- **Per-strategy overrides** are allowed but can only be **stricter** than the active account-level profile.
- **Backtests can run the same strategy under several profiles** side by side, so I can compare them.
- **Switching the live risk profile** requires a manual CLI command from me. It is logged and announced on Discord. Agents may **propose** profile changes but never apply them.
- Config is validated with typed schemas (e.g. pydantic). Invalid config means the system refuses to start.

## 8. Agents and the self-improvement loop

The system "gets better on its own" through a **gated loop**, not by modifying itself live:

1. **Journal**: the system records every decision and outcome (§4.2).
2. **Review**: once a week I run a Claude Code command (e.g. `/weekly-review`). The **Review agent** reads the journal, performance data and backtest reports, then writes a **structured proposal file**: the change, the evidence behind it, the expected effect and the risks. Proposals can cover parameter tweaks, new filters, retiring a strategy, a new strategy idea or a risk-profile change.
3. **Automated gate**: the system turns each proposal into a candidate config and runs a walk-forward backtest against the current version. If it passes, the candidate runs in paper alongside the current version (a "shadow" run).
4. **Human approval**: I approve or reject. Promotions are versioned, and the decision is logged as part of the strategy lifecycle.

Agent design requirements:
- Agents live in `.claude/commands/` (and/or skills) as Claude Code commands, plus a Python-side `LLMProvider` interface (`claude-code` default; `ollama` and `anthropic-api` as future adapters) so they can be swapped through config.
- Agent inputs and outputs are **files with JSON schemas**, validated on read. Agents never touch broker credentials, live orders or the risk config.
- Suggested agents: **Research analyst** (writes notes on the universe and candidates), **Performance reviewer** (the weekly review), **Strategy proposer** (new ideas as `draft` strategies). Keep the set small and well-defined.
- Document the agent architecture explicitly (roles, contracts, how data flows between them, why they're kept out of the trading path), since learning this is goal #1.

## 9. Notifications

- **v1: Discord webhook.**
  - **Daily summary:** trades, positions, P&L vs the benchmark, risk status, and anything skipped.
  - **Alerts:** risk limit hit, kill switch, reconciliation mismatch, gateway needs re-login, data failure, run failed or didn't happen.
- **Later phase:** a Discord bot with `/status`, `/kill`, `/resume`, etc. It only responds to my user ID, and destructive commands need confirmation.
- Notifier is an interface, so other channels can be added later.

## 10. Tech stack (suggested; challenge it if you have good reasons)

Python 3.12+, `uv`, pydantic / pydantic-settings, pandas or polars, `ib_async`, `exchange_calendars` (or `pandas_market_calendars`), APScheduler (or cron in the container), SQLite and DuckDB, Parquet, pytest (plus hypothesis for the risk layer), ruff, mypy (strict in the core), Docker compose. Later: FastAPI plus React (Vite) for the dashboard, `ccxt` for Kraken.

## 11. Documentation (part of the definition of done)

**A task is not done until its docs are updated.** Diagrams in Mermaid.

- `CLAUDE.md`: the agent's entry point. It covers the repo map, how to run, test and backtest, conventions, the **never-do rules** (never bypass the risk layer, never enable live, never commit secrets, never edit guardrails without approval) and where to find everything else.
- `docs/user-guide/`: **step-by-step guide for me as a user**:
  - installation and first-time setup (IBKR paper account, gateway, Discord webhook, `.env`, choosing market and risk profiles);
  - the daily and weekly routine;
  - reading Discord reports;
  - running a backtest and reading the report;
  - creating or comparing risk profiles;
  - running the weekly review and approving proposals;
  - promoting a strategy from paper to live;
  - using the kill switch;
  - troubleshooting and FAQ.
- `docs/developer-guide/`: **for me as a developer**:
  - what every folder and module holds;
  - the end-to-end flow of the app, with diagrams (an event's path from data to fill);
  - the pipeline stage contracts;
  - how-tos for adding a strategy, data provider, broker, notifier, agent or market profile;
  - testing strategy and coding conventions.
- `docs/architecture/`: system overview, event catalog, agent architecture.
- `docs/adr/`: one short decision record per significant decision (context, decision, alternatives, consequences).
- `docs/runbooks/`: start/stop, crash recovery, gateway re-auth, kill switch, reconciliation mismatch, paper-to-live promotion.
- `docs/learning/`: short notes explaining the patterns used (event-driven design, hexagonal architecture, the agent loop, walk-forward testing, etc.) in plain language, tied to where they appear in the code. This serves goal #1.
- `CHANGELOG.md` and `STATUS.md` (current phase, what works, what's next, known issues). Read `STATUS.md` at the start of every session and update it at the end.

## 12. Testing

- Unit tests for every core module. Property-based tests for the risk layer (no input may produce an order that breaks the active profile or the guardrails).
- Golden-file backtest regression tests, plus the reference-library validation test.
- `SimBroker` tests for fills, partial fills, rejections and currency handling.
- IBKR paper integration tests, marked and opt-in. **No automated test ever touches a live account.**

## 13. Roadmap

Stop at the end of each phase for my review. Update `STATUS.md` and the docs before stopping.

- **Phase 0: Plan.** Architecture doc, event catalog, folder structure, ADRs for key decisions, `CLAUDE.md`, `STATUS.md`, docs skeleton, repo scaffolding (tooling, CI with lint, types and tests). No business logic.
- **Phase 1: Core and backtesting (`US`, end of day).** Event bus, clock, calendars, data provider and cache, universe, strategy plugin interface, benchmark and example strategies, portfolio construction across several strategies, `SimBroker`, cost model, backtester, reports, walk-forward, reference validation.
- **Phase 2: Risk and paper trading.** Risk layer with named profiles and guardrails, profile comparison in backtests, IBKR paper adapter, execution, reconciliation, scheduler, catch-up rule, journal, Discord webhook, kill switch, Docker, user guide for running in paper.
- **Phase 3: Agents and the improvement loop.** Claude Code commands, `LLMProvider` interface, proposal schema, automated gate (walk-forward plus shadow paper), approval flow, strategy lifecycle.
- **Phase 4: Canadian markets.** `CA` and `CA+US` profiles, TSX data and calendar, CDR support, currency-conversion policy, tax-ready CAD export.
- **Phase 5: Visibility.** FastAPI plus a local React dashboard, Discord bot commands.
- **Phase 6: Expansion.** Kraken (crypto, 24/7 calendar) as a second broker, which proves the broker abstraction works, then intraday data and strategies.

Going live is **not** a phase you carry out. It's a runbook I follow myself once a strategy has met the promotion criteria.

## 14. How to work with me

- Start every session by reading `CLAUDE.md` and `STATUS.md`.
- Work in small, PR-sized steps with tests. Commit with clear messages.
- When you introduce an architectural pattern, explain it in 2–4 sentences and add or update its note in `docs/learning/`.
- When something is ambiguous or a decision is hard to reverse, ask me instead of guessing.
- Check anything about external services (IBKR API behaviour, fees, data-source limits, library versions) against current docs. Don't rely on memory.
- Prefer boring, explicit code over magic. This system handles money.

---

## Your first task

1. Ask me any clarifying questions you need, **one at a time**, about anything in this brief that is unclear or that you think is a mistake.
2. Then produce **Phase 0 only**: architecture doc, event catalog, folder structure, ADRs, `CLAUDE.md`, `STATUS.md`, docs skeleton and repo scaffolding.
3. Stop and wait for my review before starting Phase 1.
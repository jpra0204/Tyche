# ADR-0046: A local web console

- **Status:** Accepted (Pablo, 2026-11-25, with the console plan U1 to U5)
- **Date:** 2026-11-25

## Context

Pablo runs Tyche from the terminal: `tyche config check`, `data fetch`, `backtest`, `walk-forward`, `sweep`, `capital`, `compare-profiles`, `report`, `paper run`, `kill`, `resume`. On 2026-11-25 he asked for a page to run the same workflow from: choose the options, run, see the result. He wants it in React, organised so it can grow with each new feature.

Tyche's rules that a console must keep:

- **No new path to the broker** ([ADR-0006](0006-target-positions-with-optional-stops.md), CLAUDE.md rule 2). Orders reach IBKR only through the paper cycle and the risk gate.
- **No live trading from code** ([ADR-0013](0013-live-trading-gate.md)). Arming live is a manual procedure; a button would be code doing it.
- **Agents never run the paper cycle, `kill` or `resume`** on Pablo's workspace (CLAUDE.md). A server on his machine that runs them on request is something any local process could call.
- **The core stays pure** ([ADR-0004](0004-hexagonal-architecture.md)): no web framework below the top layer.

Library facts, read from the npm and PyPI registries on 2026-11-25: React 19.3.1 (MIT), Vite 8.3.8 (MIT; needs Node 20.19+ or 22.12+; this Mac has 22.23.4), TypeScript 7.0.2 (Apache-2.0), Mantine 9.8.2 (MIT; needs React 19.2+), TanStack Query 5.108.4 (MIT), React Router 8.5.3 (MIT); FastAPI 0.165.0 (MIT, lists Python 3.14), uvicorn 0.54.0 (BSD-3-Clause, lists Python 3.14), httpx 0.28.1 (BSD-3-Clause). All free.

## Decision

1. **Two parts, one command.** A React single-page app in `ui/` at the repository root (TypeScript, built by Vite), and a small HTTP API in `tyche.api` (FastAPI, served by uvicorn). `tyche ui` builds nothing: it serves the built app and the API together on `127.0.0.1`, prints the address, and opens the browser. `make ui` builds the app.

2. **The API is a second front door beside the CLI.** `tyche.api` sits in the top layer with `tyche.cli` (the layers contract becomes `tyche.cli | tyche.api`), and calls nothing the CLI does not. Reading is direct: config check, kill switch and halts, run records, checkpoints, report files.

3. **Running is the CLI itself.** A run started from the page (a backtest, a fetch, the paper cycle) is the same `tyche` command, started as a subprocess with the options the form chose. Its output streams to the page; its results are read back from what it wrote (`reports/`, the state database). The page can never do what the command cannot, and the two cannot drift apart. One run at a time: a second is refused while one is running.

4. **Local and locked.** The server listens on `127.0.0.1` only. Each launch makes a random token, put in the address it opens; every API call must carry it. Another web page, or another program on the machine, cannot drive the console without reading Pablo's terminal. Agents never start `tyche ui` on Pablo's workspace, and never call it.

5. **What it never does.** Arm or run live trading. Edit the guardrails (read-only, as a page). The paper cycle, `kill` and `resume` each ask for confirmation in the page, as the CLI asks.

6. **Mantine for components**, with TanStack Query for data from the API and React Router for pages. Mantine ships the admin pieces this needs (forms with validation, tables, tabs, notifications, a code view for output) without a CSS toolchain. TypeScript types for the API come from FastAPI's OpenAPI schema, so a change on one side fails the other's type check.

7. **Folders, one per feature.**

   ```text
   ui/                       the React app
   ├── src/
   │   ├── main.tsx          entry: Mantine, Query and Router providers
   │   ├── app/              the shell: layout, navigation, routes
   │   ├── api/              the typed client, generated from the API's schema
   │   ├── features/         one folder per workflow, each with its pages and parts
   │   │   ├── status/       workspace, config check, kill switch, halts
   │   │   ├── runs/         a running command and its output
   │   │   ├── backtests/    backtests, walk-forward, sweeps, capital, profiles
   │   │   ├── data/         fetching market data
   │   │   └── paper/        the paper cycle, the account, reconciliation
   │   ├── components/       parts shared by features
   │   └── lib/              formatting (money, dates), small hooks
   ├── package.json          exact versions; package-lock.json committed
   └── vite.config.ts        builds into dist/ (ignored); the dev server passes /api on
   src/tyche/api/            the HTTP API: app, token check, models (the contract), one module per page
   tests/api/
   ```

8. **Checked in CI** like the rest: the API's tests with pytest (Starlette's test client, which needs `httpx2`, test-only); the app's type check, lint and build in a new CI job; a test that the committed `openapi.json` matches the API. No end-to-end browser tests at first.

## Alternatives considered

- **A Python-only UI (Streamlit, NiceGUI).** Faster to start, one language, but not React, which Pablo asked for, and harder to organise as it grows.
- **shadcn/ui or MUI instead of Mantine.** shadcn/ui copies components into the repository and needs Tailwind; MUI is larger and its richest pieces (data grid, date pickers) have paid tiers. Mantine is MIT throughout.
- **Calling `tyche.runtime` in a background thread** instead of a subprocess. Less overhead, but a long run would share the server's process, a crash would take the console down, and the CLI's own checks and output would be redone in a second place.
- **No token, localhost only.** Any web page Pablo opens can send requests to `127.0.0.1`; without a token one could start a paper cycle.

## Consequences

- New runtime dependencies `fastapi` 0.165.0 and `uvicorn` 0.54.0 (with `starlette` 1.10.0, BSD-3-Clause), and `httpx2` 2.16.2 (BSD-3-Clause, from the pydantic project) for tests: Starlette 1.10's test client asks for `httpx2` instead of `httpx`, read when building U1. Node and npm for building the app; `ui/package-lock.json` committed.
- **TypeScript is held at 5.9.3**, not 7.0.2: typescript-eslint 8.74.0 accepts TypeScript below 6.1, and openapi-typescript 7.13.0 needs 5.x (npm, 2026-11-25). Revisit when both support 7.
- The app's 210 npm packages are all under permissive licences (MIT, ISC, BSD, Apache-2.0, 0BSD, BlueOak); `lightningcss`, Vite's CSS tool, is MPL-2.0, used unmodified at build time only.
- A second language in the repository, with its own lint and type check in CI.
- CLAUDE.md gains `tyche ui` and the rule that agents never start or call it on Pablo's workspace.
- Every new command later gets its form in the console in the same PR, or the console falls behind the CLI.

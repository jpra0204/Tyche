# ADR-0002: Python 3.14, pinned with uv

- **Status:** Accepted (brief)
- **Date:** 2026-11-16

## Context

The brief requires Python 3.12 or newer, pinned per project with `uv`, never the system Python. The rule for choosing the version is: use 3.14 if every dependency supports it, otherwise the newest version they all support. The same version must be used in the Docker image.

## Decision

**Tyche uses Python 3.14.** It is pinned in `.python-version`, required by `pyproject.toml` (`requires-python = ">=3.14"`), and used by CI through `uv`. The Docker image (Phase 2) will use the matching `3.14` base image.

**Verification.** On 2026-11-16, in a throwaway project on CPython 3.14.6 (macOS arm64), every dependency planned for Phases 1 to 3 resolved, installed and imported:

| Package | Version | Package | Version |
|---|---|---|---|
| pydantic | 2.14.3 | ib_async | 2.1.0 |
| pydantic-settings | 2.16.3 | yfinance | 1.8.0 |
| pandas | 3.1.1 | apscheduler | 3.11.3 |
| pyarrow | 26.0.1 | httpx | 0.28.1 |
| duckdb | 2.0.0 | structlog | 26.1.0 |
| exchange_calendars | 4.13.3 | hypothesis | 6.170.15 |
| backtesting | 0.6.6 | vectorbt | 1.2.1 |
| pytest | 9.2.0 | mypy | 2.4.1 |
| ruff | 0.17.5 | import-linter | 2.16 |

This proves the packages install and import on 3.14. It does not prove every feature works; each library gets real tests in the phase that first uses it.

**Dependencies are added when first used.** `pyproject.toml` lists only what the code imports today (Phase 0: development tools only). The table above is a feasibility check, not the dependency list.

**Tooling.** `uv` manages the interpreter, the virtual environment and the lockfile (`uv.lock`, committed). Ruff lints and formats, mypy type-checks in strict mode, pytest runs tests, import-linter checks the architecture.

## Alternatives considered

- **Python 3.13 or 3.12**, for a more conservative base. Not needed: nothing we plan to use fails on 3.14.
- **pip with venv, or Poetry.** `uv` is the brief's choice, pins the interpreter as well as the packages, and is fast enough to make CI trivial.

## Consequences

- One version everywhere: laptop, CI and Docker.
- If a later dependency does not support 3.14 (Kraken's `ccxt` in Phase 6 has not been checked yet), we either wait, pick an alternative or lower the pin with a new ADR.
- Linux wheels for the same packages will be confirmed when the Docker image is built in Phase 2; the check above ran on macOS.

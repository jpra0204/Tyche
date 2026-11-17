# Conventions

The rules for writing code in Tyche. Most are enforced by tools; the rest are checked in review.

## Guiding rule

Prefer boring, explicit code over clever code. This system handles money, and the main goal of the project is that Pablo understands every part of it.

## Code

| Rule | Enforced by |
|---|---|
| Python 3.14, run through `uv run` | `.python-version`, CI |
| Formatting and import order | `ruff format`, `ruff check` |
| Type hints on everything, strict mode | `mypy` |
| Absolute imports only | ruff `TID` |
| No naive datetimes; time comes from the `Clock` port | ruff `DTZ`, review |
| `pathlib` instead of `os.path` | ruff `PTH` |
| Dependency direction | `import-linter` |

Further rules checked in review:

- **No mode checks in the core.** Never `if backtest:`. Differences between modes come from ports.
- **Money is `Decimal` with a currency;** market data and analytics are `float` ([ADR-0012](../adr/0012-money-and-time-types.md)).
- **Events are frozen dataclasses** that subclass `Event` and are named `SomethingEvent`; the bus rejects anything else. An event holds its own facts only; the bus adds the envelope.
- **Handlers only publish.** A handler never calls another component and never drains the bus.
- A new or changed event updates the [event catalog](../architecture/event-catalog.md) in the same PR.
- **Ports are `typing.Protocol` classes.** Adapters do not inherit from core classes.
- **Fail closed.** When something unexpected happens in the trading path, stop and alert. Do not guess and continue.
- **No secrets in code, logs or tests.** Log an account id or URL only in a masked form.
- **Comments explain why,** not what. Public modules, classes and functions have a docstring.
- **A dependency is added in the PR that first uses it,** with a line in the PR description saying why. Anything that costs money is flagged to Pablo before it is added.

## Testing

| Kind | Purpose | Where | Phase |
|---|---|---|---|
| Unit | Every core module, tested through its public interface with fakes for ports | `tests/core/...` | 1 onward |
| Property-based (hypothesis) | The risk layer: no generated input may produce an order that breaks the active profile or the guardrails | `tests/core/risk/` | 2 |
| Golden-file regression | A fixed backtest must reproduce its stored event log and metrics exactly | `tests/core/backtest/` | 1 |
| Reference validation | Our backtester agrees with an independent library on a simple strategy | `tests/core/backtest/` | 1 |
| Simulator | `SimBroker` fills, partial fills, rejections, stops, settlement, currency | `tests/core/sim/` | 1, 4 |
| Architecture | Import contracts | `make imports` | 0 |
| IBKR paper integration | Real calls against the paper account; opt-in | marked `ibkr_paper` | 2 |

Rules:

- Tests are deterministic. No real network, no real clock, no sleeping. Randomness uses a fixed seed.
- Every folder under `tests/` has an `__init__.py`, so two test files may share a name in different folders.
- The `ibkr_paper` marker is deselected by default. Run those tests on purpose with `uv run pytest -m ibkr_paper`.
- **No automated test ever touches a live account.**
- A bug fix comes with a test that fails without the fix.

## Git and pull requests

Recorded in [ADR-0014](../adr/0014-git-workflow-and-ci.md).

- One branch per increment, named `phase-N/short-description`.
- Commits have a short imperative subject ("Add event envelope") and a body that explains why.
- Each PR is small enough to review in one sitting and passes `make check`.
- Pablo reviews and merges. Nothing is pushed to `main` directly.

## Definition of done

A task is done when all of these are true:

1. The code is merged-ready and `make check` passes.
2. New behaviour has tests.
3. Docs are updated: the relevant guide page, the event catalog if events changed, and an ADR if a significant decision was made.
4. A new pattern has a 2 to 4 sentence explanation in the PR and a note in [`docs/learning/`](../learning/README.md).
5. `STATUS.md` and `CHANGELOG.md` reflect the change.

## Documentation style

- Plain language. Write for a capable developer who is new to trading systems.
- Diagrams are Mermaid.
- Facts about external services (fees, API behaviour, limits) are stated only after checking a current source, with the date checked.
- No placeholder pages. A planned page is listed in its folder's index until it is written.

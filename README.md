# Tyche

*Named after Tyche, the Greek goddess of fortune.*

Tyche is an event-driven trading framework for one person running their own strategies on their own machine. The trading path is plain, tested Python. LLM agents help with research and review, and can only produce proposals that pass an automated backtest gate and a human approval before anything changes.

> **Status: Phase 0 (plan and scaffolding).** There is no trading functionality yet. See [`STATUS.md`](STATUS.md).

## Principles

- **Same code in backtest, paper and live.** Only the clock, the data feed and the broker are swapped.
- **Risk is a gate nothing bypasses.** Named risk profiles sit under hard guardrails that no profile can exceed.
- **No LLM in the trading path.** Agents write proposals; code and a human decide.
- **A strategy must prove itself** against buy-and-hold, after costs, out of sample.
- **Live trading is only ever switched on by hand.**

## Getting started (development)

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python version for you.

```bash
git clone https://github.com/jpra0204/Tyche.git
cd Tyche
make install
make check
uv run tyche --version
```

To create your private workspace, follow the [installation guide](docs/user-guide/01-installation.md).

## Documentation

| | |
|---|---|
| [System overview](docs/architecture/system-overview.md) | How the whole system fits together |
| [Event catalog](docs/architecture/event-catalog.md) | Every event, who publishes it and who consumes it |
| [Agent architecture](docs/architecture/agent-architecture.md) | How the LLM agents work and why they are isolated |
| [Decision records](docs/adr/README.md) | Why each significant decision was made |
| [Developer guide](docs/developer-guide/README.md) | Repo map, conventions, testing, how-tos |
| [User guide](docs/user-guide/README.md) | Setup and the daily and weekly routine |
| [Runbooks](docs/runbooks/README.md) | What to do when something needs attention |
| [Learning notes](docs/learning/README.md) | The patterns used, in plain language |

## Disclaimer

Tyche is a personal software project. Nothing in this repository is financial, investment or tax advice. The example strategies exist to exercise the framework and are not expected to make money. Trading can lose money, including all of it.

## Licence

No licence has been chosen yet, so all rights are reserved for now.

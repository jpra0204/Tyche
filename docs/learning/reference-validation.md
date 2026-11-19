# Reference validation

## What problem does this solve

A test checks code against what its author expected. If the author misunderstood a rule (when an order fills, what a commission costs, how a drawdown is measured), the code and its test agree, and both are wrong. The golden file ([golden-file tests](golden-files.md)) has the same blind spot: it records what the code did once and guards against change, not against a mistake that was there from the start.

For a backtester this matters more than usual. Its output is a number nobody can check by eye, the number decides whether real money is risked, and the usual mistakes (filling at a price the strategy could not have had, charging costs once instead of twice) all make results look better.

## The idea

Run the same scenario through a second implementation written by other people, and compare the outputs. This is **differential testing**: two independent programs that should agree, checked against each other. Agreement is good evidence, because two independent authors rarely make the same mistake in the same way. A disagreement is a bug in one of them, and finding which one teaches you something either way.

Four things make it work:

- **Line the two up honestly.** The engines differ in what they model. Compare only what both model, map the rest explicitly (Tyche charges slippage on every fill; backtesting.py only moves the entry price, so the comparison charges slippage as commission, which moves the same cash), and write down what is left out.
- **Write the rule twice.** The strategy is written once for each engine, against each one's own view of history. If one engine handed its decisions to the other, the comparison would only check the arithmetic after the decision.
- **Compare everything you can, not just the final number.** A final balance can agree by coincidence. Every fill, the equity at every close and every closed trade cannot.
- **Prove the test can fail.** Break one side on purpose (a wrong minimum commission, a decision one bar late) and watch the comparison catch it. A comparison that always passes protects nothing.

## Where is it in Tyche

- `tests/reference/comparison.py` runs `AboveItsAverage` (hold 95% of equity while the close is above its recent average) through Tyche's `run_backtest` and through [backtesting.py](https://kernc.github.io/backtesting.py/), then compares fills, equity, trades and metrics. Its docstring lists what is mapped and what is left out.
- `tests/reference/test_backtesting_py.py` runs it in CI on a seeded random walk at two account sizes, and on demand on 19 years of real SPY bars (`uv run pytest -m network`).
- The decision and its limits are in [ADR-0026](../adr/0026-reference-validation-against-backtesting-py.md).
- backtesting.py is AGPL-3.0, so it is a development dependency only. An import-linter contract fails CI if any module of Tyche imports it.

## What does it cost

- **Only the common ground is checked.** backtesting.py has no dividends, no settlement, no stops placed the way Tyche places them, and one position at a time. Those parts of Tyche still rely on their own tests.
- **The mapping is code too.** The commission function written for backtesting.py could have its own mistake. It is written from IBKR's published schedule, not copied from Tyche, so a mistake there shows up as a disagreement rather than hiding one.
- **A dependency to keep.** A new release of the reference can change its behaviour or raise new warnings. Pin it, and read its changelog before upgrading.
- **Agreement is not correctness.** Two engines can share a modelling choice that is wrong for the real market, such as filling every market order at the official open. Paper trading (Phase 2) checks the model against a real broker.

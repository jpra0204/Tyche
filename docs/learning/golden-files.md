# Golden-file tests

## What problem does this solve

A backtest's result depends on dozens of rules: when orders fill, what they cost, how cash settles, how each metric is defined. Unit tests check each rule alone, but a small change to one of them can move the final numbers in a way no single test notices. In a system that handles money, a number that changes without anyone deciding it should is a bug until proven otherwise.

## The idea

Run a fixed, deterministic scenario end to end, save every output number in a file committed to the repository (the **golden file**), and compare each later run with it exactly.

- If nothing should have changed, the test passes.
- If something changed by accident, the test fails and points at which numbers moved.
- If the change is intended (a fixed bug, a new cost rule), you regenerate the file **on purpose**, and the diff in the pull request shows every number that moved. The reviewer checks that each move makes sense.

Three conditions make it work:

- **Deterministic inputs.** Made-up prices from a formula, a fixed calendar, no network, no wall clock.
- **Deterministic arithmetic.** Tyche's metrics use `Decimal` in a fixed context, so the last digit is the same on every machine. With `float`, platform differences in the last digits would make the file flaky.
- **A scenario that exercises everything.** A golden file of zeros and `null`s protects nothing. A second test checks that every figure in it is a real number.

## Where is it in Tyche

- `tests/integration/test_backtest_to_metrics.py` runs two sleeves on wavy prices with quarterly dividends, with one strategy that opens and closes trades. It sends the result through `metrics.json`'s serialiser and compares it with `tests/integration/golden/backtest_metrics.json`.
- To regenerate after an intended change:

  ```bash
  TYCHE_UPDATE_GOLDEN=1 uv run pytest tests/integration/test_backtest_to_metrics.py
  ```

  Then read the diff before committing it.

## What does it cost

- **It says that something changed, not whether it is right.** The golden file's numbers were checked by hand and against an independent calculation once; after that, it only guards against change.
- **Regenerating can become a reflex.** If every failing run is "fixed" by regenerating, the test protects nothing. Each regeneration needs a reason in the pull request.
- **It is brittle on purpose.** Any rounding change touches it. That is the point.

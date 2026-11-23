# Property-based testing

## The problem

An ordinary test checks one example you thought of:

```python
account = funded("10000").apply_fill(buy 10 at 100, commission 1)
assert account.cash(USD).total == usd("8999")
```

That proves the ledger works for that one trade. It says nothing about the trades you did not think of: a third of a share, a price of one cent, thirty fills in a row with partial sales in between. Bugs live in exactly those cases, because you did not think of them while writing the code either.

## The idea

Instead of an example, write down a **rule that must hold for every input**, then let a library generate inputs and try to break it. When it finds a counter-example, it shrinks it to the smallest one that still fails and prints it.

For a ledger, the rules are short:

| Property | In words |
|---|---|
| Cash is conserved | The deposit plus every fill's cash flow equals the cash balance, exactly |
| No shorts | No sequence of trades leaves a negative position |
| Settlement only moves cash | Settling changes what is settled, never the total |
| Every dollar is accounted for | Cash = deposit + realised profit − cost of the shares still held |
| A round trip costs the fees | Buying and selling the same quantity at the same price loses exactly the two commissions |

Each property is one test, and the library runs it against 200 generated sequences of trades.

If you have used fuzzing in front-end work, such as feeding random strings into a form parser, this is the same idea with more structure: the generated inputs follow the shapes you describe, and failures are minimised for you.

## A real catch

The first run of these tests failed on the fourth property. Hypothesis printed a sequence of small buys and partial sales after which:

```text
828879.41694  !=  828879.4169399999999999999999
```

A difference of 0.00000000000000000001 USD. The cause: selling part of a position allocates it `cost × sold ÷ held` of the cost, and that division often never ends (selling a third). Python's `Decimal` rounds it at 28 significant digits. Over many sales, adding numbers of different sizes rounds differently on each side, and the books stop balancing exactly.

No example test would have caught it, and in dollars it does not matter. But a ledger that only *almost* reconciles hides real errors behind rounding noise, so the fix is a rule: the cost allocated to a sale is rounded to ten decimal places (`COST_PLACES` in `tyche.core.domain.account`). After that every amount is a finite decimal, sums are exact, and the property holds on every run.

## Where it is in Tyche

- Ledger properties: `tests/core/domain/test_account_properties.py`.
- Settings: `tests/conftest.py` runs hypothesis from a fixed seed, so every run tries the same examples. Tests stay repeatable, as the conventions require.
- The risk gate: `tests/core/risk/test_gate_properties.py`. Its properties are the most important in the project: no proposal, holdings or limits of any kind may produce an approved portfolio that breaks the active risk profile (and so the guardrails above it). The gate's rules are a pure function, which is what makes this practical ([functional core](functional-core.md)).
- **Check that a property can fail.** A property that passes no matter what proves nothing. For the gate, each rule was switched off in turn, and a property failed every time. Do the same when you add a property that guards something important.
- Next: the order-level guardrails (Phase 2, PR 3): no order may exceed the money caps.

## What it costs

- **Writing a good property is harder than writing an example.** You have to know what is always true, which forces you to understand the code. That is part of the value.
- **Slower tests.** 200 examples per property instead of one. For the ledger that is about a second in total.
- **A property can be too weak.** "Cash never goes below zero" would pass a ledger that never records anything. Pair properties with a few example tests that check real numbers.

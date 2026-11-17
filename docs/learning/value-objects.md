# Value objects

## The problem

The simplest way to pass data around is with primitives: a price is a `float`, a ticker is a `str`, an amount of money is a number. It works, and it lets several kinds of mistake through without a sound:

```python
cash = 1000.0  # which currency?
cash = cash - 142.37  # float: the cents will drift
total = usd_cash + cad_cash  # adds happily, means nothing
bar_time = datetime(2024, 7, 3)  # midnight where? known when?
```

None of these lines raises an error. Each one produces a wrong number that looks like a right one, and in a trading system a wrong number becomes a wrong order.

## The idea

Wrap each concept in a small type that **cannot hold an invalid value**. Three properties define a value object:

1. **It validates itself when it is created.** If construction succeeds, the object is valid. Code that receives one never has to check it again.
2. **It is immutable.** Nothing can change it afterwards, so it can be shared, stored in an event and replayed later without anyone worrying about who else holds it.
3. **It is equal by value.** Two `Money` objects holding 5 USD are the same thing. There is no identity beyond the contents.

The phrase to remember is *make illegal states unrepresentable*. Instead of writing checks wherever money is used, you make it impossible to build the bad value in the first place.

If you use TypeScript, this is the idea behind a branded type, or behind parsing an API response with a schema once at the edge and trusting the typed result everywhere after. Python's version is a frozen dataclass with a `__post_init__` check.

```python
@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency
```

`frozen=True` makes it immutable and gives it value equality and a hash. `slots=True` stops anyone attaching extra attributes and saves memory.

## Where it is in Tyche

All in `tyche.core.domain`:

| Type | What it makes impossible |
|---|---|
| `Currency` | A misspelled currency code |
| `Money` | Float amounts; adding or comparing two currencies; silent rounding |
| `Timeframe` | An unknown bar period; assuming a daily bar has a fixed length |
| `Instrument` | A malformed symbol or exchange code; guessing an instrument's currency or calendar |
| `Bar` | A naive or non-UTC timestamp; a zero, negative or NaN price; a high below the close; negative volume |

Three choices worth understanding:

- **`Money` refuses floats everywhere.** `Money.of(1.1, ...)` and `money * 1.1` are both errors. You pass a `Decimal`, an `int` or a string such as `"12.34"`. This is [ADR-0012](../adr/0012-money-and-time-types.md) turned into code.
- **Dividing money by money gives a plain number.** `position_value / equity` is a weight, and a weight has no currency. Dividing by a number gives money back.
- **A bar's timestamp is its close, in UTC.** That is the moment the bar became known. Later, "could the strategy have known this yet?" becomes a comparison between a timestamp and the clock.

Bad data from a vendor does not vanish because `Bar` rejects it. The data adapter is the place that catches the error, reports it and decides what to do (Phase 1, PR 5). The value object guarantees that nothing past the adapter ever sees it.

## What it costs

- **More code than a tuple or a dict.** `Money` is about a hundred lines for something a float does in zero.
- **Conversion at the edges.** Data from pandas or a broker API has to be turned into these types on the way in and back out on the way to a report.
- **Slower than raw numbers.** Creating a validated object per bar costs time. For daily bars it is not measurable. For large intraday backtests it might be, and the answer then is to validate in bulk at the adapter, not to drop the types.
- **Rigidity.** Adding a currency means editing the enum. That is intended: it should be a deliberate act.

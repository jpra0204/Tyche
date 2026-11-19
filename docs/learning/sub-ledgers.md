# Sub-ledgers that add up: sleeves, crossing and netting

## The problem

Several strategies share one brokerage account. The broker knows only the account: 60 SPY, 25 QQQ and some cash. Tyche needs to know more:

- **Which strategy owns which shares.** A strategy decides from its own positions (ADR-0021). If buy-and-hold and a trend strategy both hold SPY, each must see only its own shares, or one will "sell" what the other bought.
- **Each strategy's results**, to compare it with the benchmark.

The simplest answer, a separate order stream per strategy, is expensive. If one strategy sells 4 SPY while another buys 10, two orders pay two minimum commissions. For a small account that is about 1% of each order.

## The idea

**Keep a sub-ledger per strategy that always adds up to the real account, and trade the account only for the difference.**

Accountants call this a subsidiary ledger: customer balances kept one by one, which must sum to the "accounts receivable" line in the general ledger. In Tyche, each strategy's sleeve is a sub-ledger of shares, and the account is the general ledger.

At each decision, for each instrument:

1. **Work out each sleeve's target** in whole shares.
2. **Cross first.** If sleeve B gives up 4 shares and sleeve A wants 10, move B's 4 shares to A *inside the book*, at the last close. Nothing reaches the broker, and no commission is paid. Funds and banks do this between their own accounts; it is called an internal cross.
3. **Net the rest.** The remaining 6 shares go out as one order, serving A only.
4. **Split fills pro rata.** If only some of the order fills, or several sleeves are on the same side, each sleeve gets shares in proportion to what it is still owed. A fixed priority would make the same strategy absorb every shortfall.
5. **Check the invariant.** Before every decision, the sleeves must add up to the account's positions, share for share. If they do not, something is wrong, and Tyche halts rather than trade on a broken book.

The invariant is what makes the scheme safe. Crossing and splitting are bookkeeping, and bookkeeping errors are silent. A sum checked before every decision turns a silent error into a loud one.

## Where it is in Tyche

| Piece | Where |
|---|---|
| The decision | [ADR-0023](../adr/0023-execution-sleeves-stops-and-cash.md), building on [ADR-0022](../adr/0022-portfolio-targets-as-weights-in-sleeves.md) |
| The sleeve book (shares, entry, average price, resting stop per sleeve) | `SleeveBook` in `tyche.core.pipeline.execution.sleeves` |
| Crossing, netting and the invariant check | `ExecutionStage` in `tyche.core.pipeline.execution.stage` |
| The pro-rata rule, in whole shares, exact | `split_pro_rata` in `tyche.core.pipeline.execution.allocation`, with a property-based test |
| The account the sleeves must add up to | `AccountState`, built from the same fills as the broker's own record |

## What it costs

- **Attribution is approximate.** A crossed share changes sleeve at the decision's close, while a real order would fill at the next open. The account's totals are exact; how the profit is split between strategies is off by one night's price move on the crossed shares.
- **More state to get right.** A sleeve book is state that must survive restarts in paper and live trading (Phase 2), and it must be rebuilt or reconciled if it is ever lost.
- **Crossing assumes the strategies share one account and one risk budget.** If they ever trade in separate accounts, crossing between them stops being possible.

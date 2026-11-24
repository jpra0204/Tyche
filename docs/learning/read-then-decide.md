# Read, reconcile, then decide

**The pattern:** before a system acts on the outside world, it first takes in everything the outside world did since it last looked, checks its own record against the world's, and saves that. Only then does it decide. And when two of its own actions could collide out there, it holds the second until the first is confirmed gone.

## Why it matters here

A paper run starts hours after the last one. In between, IBKR filled orders at the open, perhaps cancelled a stop by itself, perhaps charged a fee. If Tyche decided first, it would size its orders on an account that no longer exists: it might try to sell shares it already sold, or buy with cash it already spent. So `tyche paper run` is two runs in one evening ([ADR-0045](../adr/0045-the-paper-cycle.md)):

1. **The check.** Read IBKR's fills into Tyche's stages, compare the result with IBKR's own record ([reconciliation](reconciliation.md)), correct or halt, and **save**.
2. **The decision.** Build the stages again *from what the check saved*, so the risk gate sees any halt the check found, and only then decide.

Saving between the two matters because IB Gateway reports only today's executions. Fills read and then lost to a failed decision could never be read again.

## Holding what could collide

The second idea is smaller and sharper. When Tyche exits a position, it sells the shares and cancels the stop that protected them, in that order, in one decision. IBKR confirms a cancellation a little later, not at once. If the sale went out while the stop was still working, both could sell the same shares, which a cash account cannot do.

The adapter cannot judge a sale when it sees it, because the cancellation has not been asked for yet. So it **holds every new sell order** until the decision has finished, then **releases** each one whose instrument has no cancellation still waiting. The cycle reads IBKR once a second until nothing is held, for at most a minute; what is still held then is rejected, never sent, and the next decision tries again.

This is a small *barrier*: the second action waits for proof that the first has taken effect, and gives up safely rather than guessing.

## In Tyche

- `tyche.runtime.paper`: `run_paper`, the check and the decision, `CANCEL_WAIT`.
- `IBKRBroker.held`, `.release()`, `.reject_held()`: the barrier.
- `IBKRBroker.forget()`: once reconciliation has dropped an order IBKR no longer lists, the adapter stops tracking it, so no sale waits on it forever.

## What it costs

- **Two runs per evening** in the journal, and the stages built twice. Cheap: building them takes milliseconds; the evening has hours.
- **A sale can be a day late** if IBKR is slow to confirm a cancellation. That is the price of never risking two sales of the same shares, and it is alerted.
- **More waiting means more moving parts to test.** The wait loop has its own tests with a scripted broker, because the fake gateway confirms nothing by itself.

# Notifications outside the trading path

**The pattern:** decide *what* to tell a person inside the system, as plain values, but do the telling at the edge, after the work is done. A message that fails to send is logged and forgotten. It never stops the work it describes.

## Why it matters here

Tyche's decision cycle is a synchronous bus ([event-driven design](event-driven-design.md)): one event at a time, and a handler that raises halts the run. A Discord call inside a handler would put a network round trip, with timeouts and rate limits, in the middle of deciding what to trade. And if Discord were down, the obvious code (`send` raises, the handler raises) would halt trading because a chat message could not be posted.

So the work is split in two:

1. **Collect.** `AlertCollector` subscribes to the bus like the journal. It only reads, and turns a few events into `Alert` values. That is pure code: easy to test, no clock, no network.
2. **Send.** After the run, the runtime hands the alerts to the `Notifier`. Each failure is caught, logged and counted. The run's result does not depend on it.

This is a small cousin of the *transactional outbox* used in distributed systems: write down what must be announced as part of the work, and announce it separately. Tyche does not retry a lost alert later. The journal and the log are the record; Discord is a convenience.

## Two smaller ideas in the same PR

- **Secrets as types.** A webhook URL is a pydantic `SecretStr`. It prints as `**********`, so `print(secrets)` or a `repr` in a traceback cannot leak it. Code that needs the value has to ask for it by name (`get_secret_value()`), which makes every use easy to find.
- **Redact at the last moment.** The log formatter replaces every secret in the finished line, after the message, the extra fields and any traceback have been rendered. A filter that cleaned only the message would miss the rest. Redaction is the second line of defence. The first is never logging a secret at all.

## In Tyche

- [ADR-0040](../adr/0040-logs-secrets-and-alerts.md): the decision.
- `src/tyche/core/pipeline/alerts/collector.py`: what becomes an alert.
- `src/tyche/runtime/notify.py`: sending, and never failing.
- `src/tyche/adapters/logs/json_lines.py`: daily JSON-lines logs with redaction.
- [How to add a notifier](../developer-guide/how-to-add-a-notifier.md).

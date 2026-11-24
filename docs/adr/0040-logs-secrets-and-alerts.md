# ADR-0040: Logs, secrets and Discord alerts

- **Status:** Proposed
- **Date:** 2026-11-23

## Context

Paper trading (Phase 2, PR 14) will run unattended after each close. Pablo needs to hear when something needs him, and needs a record of what Tyche did. The brief asks for structured logs, secrets in `.env`, a `Notifier` interface, and a Discord webhook for the daily summary and for alerts: "risk limit hit, kill switch, reconciliation mismatch, gateway needs re-login, data failure, run failed or didn't happen" (brief §9).

This PR comes before any paper run exists, so the alerts must be built and tested now and switched on later. Reconciliation, the gateway and the scheduler come in later PRs, and so do their alerts.

Pablo answered two questions on 2026-11-23, before any code:

1. **Reading `.env`:** the standard library, not `pydantic-settings`. It is about 40 lines of our own, and adds no dependency. `pydantic-settings` 2.16.3 would have brought `python-dotenv` and `typing-inspection` with it, and more ways to set one value.
2. **What PR 9 sends:** `tyche kill` and `tyche resume` post straight away, and a new `tyche notify test` checks the webhook. Runs send their alerts from PR 14 on. Backtests and the other research commands never post. The daily loss limit and the drawdown kill are alerts. Routine position-size and money-cap cuts are not: a capped position is cut at every close, 4,781 times in 19 years of buy-and-hold, so they belong in the daily summary (PR 16).

Discord's documentation, read on 2026-11-23 (docs.discord.com: `resources/webhook`, `resources/message`, `topics/rate-limits`, `reference`), sets these limits:

- A message's `content` holds up to 2,000 characters. Embeds have their own limits (6,000 characters across a message).
- `?wait=true` makes Discord confirm that the message was saved. Without it, "a message that is not saved does not return an error".
- Rate limits "should not be hard coded". Each response carries `X-RateLimit-Remaining` and `X-RateLimit-Reset-After`. A `429` says how many seconds to wait in `retry_after`.
- "If a webhook returns a 404 status you should not attempt to use it again." 10,000 invalid requests (401, 403, 429) in 10 minutes earn a temporary ban.
- HTTP clients "must provide a valid User Agent" of the form `DiscordBot ($url, $versionNumber)`, or "may be blocked".

## Decision

**Secrets.** `.env` in the workspace holds secrets only ([ADR-0010](0010-config-toml-pydantic.md)). `tyche.config.env` reads it with a deliberately small format:

- One `KEY=value` per line, optional matching quotes, nothing interpreted inside them.
- No `export`, no `${VAR}`, no comment after a value, no key twice.
- Only known keys. A misspelt key is an error, not a secret silently unused.

A variable set in the process environment wins over the file, which is how Docker will pass them in (PR 18). The values come back as a `Secrets` of pydantic `SecretStr`s, which print as asterisks. A malformed `DISCORD_WEBHOOK_URL` is refused at `tyche config check`. No error message shows a value. `tyche config check` warns when `.env` can be read by other users.

**Logs.** Each workspace command sends the `tyche` logger to `logs/<UTC date>.jsonl`: one JSON object per line, with the time, level, logger, message and named fields. The logger does not pass records to the root logger, and a library's own logging is left alone. The folder is created `0700` and each file `0600`. **The formatter redacts the finished line:**

- every secret value from `.env`;
- anything shaped like a Discord webhook URL, whether given or not.

So no message, field or traceback reaches the file with a secret in it. A command never fails because its logs cannot be written.

**The `Notifier` port** takes an `Alert`: a kind, a one-line title, a UTC time, and lines of detail. `send` delivers it or raises `NotifierError`, whose message never holds a secret. Callers catch the error, log it and carry on: **a failure to notify never stops trading or a command.**

**Alerts come from events, and leave after the run.** `AlertCollector` (in `tyche.core.pipeline.alerts`, pure code) subscribes to the bus like the journal and only reads:

- a `RiskEvent` carrying an `AccountTrigger` (the daily loss limit or the drawdown kill) is one alert;
- the first `ApprovedPortfolioEvent` carrying the kill switch is one alert per run;
- every `DataQualityEvent` of a run becomes one alert, the first ten issues listed.

The runtime sends the collected alerts once the run has ended. A run that fails cannot publish, so the runtime builds `run_failed_alert` itself. No network call happens inside a bus handler, where a slow Discord would hold up the decision cycle and an exception would halt the bus. There is still no `NotificationEvent`. `tyche kill` and `tyche resume` build their alerts directly and send them at once. The kill command writes the flag before it opens its logs or reads `.env`, so nothing can delay the switch.

**The Discord adapter** uses the standard library's `urllib`: one POST per alert, a few a day, need no HTTP client library. It:

- sends plain `content` with markdown characters escaped outside inline code, cut to 2,000 characters;
- sets `allowed_mentions` to nothing, so no text in an alert can ping `@everyone`;
- adds `?wait=true` and the User-Agent Discord asks for;
- on a `429`, waits `retry_after` (at most 30 seconds) and tries once more;
- before the next alert, waits for a bucket that `X-RateLimit-Remaining: 0` says is empty;
- after a `401`, `403` or `404`, stops using the webhook until the process restarts.

Times in alerts are in UTC, like the CLI's. Local time (ADR-0012) comes with the daily summary.

## Alternatives considered

- **`pydantic-settings` for `.env`.** Typed settings that match the TOML config's style, but two more packages and several ways to set one value. Declined by Pablo for the standard library.
- **`httpx` or `requests` for the webhook.** Pleasant APIs, but a dependency for a handful of POSTs a day. `urllib` does the job, and HTTP errors are turned into responses in one place.
- **Send each alert from inside its bus handler.** Alerts would leave a few minutes sooner, but a network call would sit inside the trading path's dispatch, and a handler that raises halts the bus. Collect-then-send keeps the cycle pure and its timing unaffected by Discord.
- **Every `RiskEvent` is an alert.** Faithful, but about one message per trading day for a capped position, which teaches the reader to ignore the channel. Declined by Pablo.
- **Embeds instead of plain text.** Colour and fields look better, but they bring a second set of limits and render poorly in notifications on a phone. They can come with the daily summary (PR 16) if it needs them.
- **Redact with a logging `Filter`.** A filter sees the message and its arguments, but extra fields and tracebacks are rendered later, by the formatter. Redacting the formatter's finished line covers all of them.
- **`TimedRotatingFileHandler`.** It renames the current file at midnight, so the newest log always has the same name and older ones get a suffix. One file per UTC day, named by the date of each record, is simpler to find and to back up, and a process that runs past midnight moves to the next file by itself.

## Consequences

- Pablo can check his webhook today (`tyche notify test`), and a kill or resume from a terminal tells the channel.
- Logs exist from now on for every workspace command, in the gitignored `logs/` folder. They are not rotated or deleted. A retention rule comes with the maintenance runbook (PR 20) if they grow.
- The paper run (PR 14) wires `AlertCollector` and `run_failed_alert` into the run. Reconciliation (PR 13), the scheduler (PR 15) and the gateway (PR 17) add their own alert kinds.
- The User-Agent names the public repository's URL, as Discord asks. Nothing else about Pablo is sent; the alert text is his own.
- If an alert is lost (Discord down, webhook deleted), the log still has it, with the reason. A lost alert is never retried later. A retry queue would be a new piece of state to reconcile, for a channel that is a convenience, not the record.

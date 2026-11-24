# Discord alerts, secrets and logs

Tyche tells you in a Discord channel when something needs you, and keeps a log of what every command did. This page covers setting up the channel, the `.env` file that holds its secret, which alerts exist, and where the logs are. Design: [ADR-0040](../adr/0040-logs-secrets-and-alerts.md).

## Set up the channel

1. In Discord, make a server for Tyche (or use one only you are in), and a text channel such as `#tyche`.
2. Open the channel's settings: **Integrations**, then **Webhooks**, then **New Webhook**. Copy its URL. It looks like `https://discord.com/api/webhooks/<id>/<token>`.
3. Open `.env` in your workspace and paste it after `DISCORD_WEBHOOK_URL=`:

   ```text
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
   ```

4. Check the file:

   ```bash
   uv run tyche config check
   ```

   Expected: a line starting `Secrets:` that says `Discord webhook set`.
5. Send a test message:

   ```bash
   uv run tyche notify test
   ```

   Expected: `Discord: test message sent. Check the channel.`, and in the channel a message *Tyche can reach this channel*.

**Anyone who has the URL can post to your channel.** Treat it like a password. Never paste it into an issue, a chat or a commit. If it leaks, delete the webhook in Discord and make a new one.

## The `.env` file

`.env` holds secrets only; every other setting is in the TOML files under `config/`. Tyche reads it with a deliberately strict format:

- one `KEY=value` per line; blank lines and lines starting with `#` are ignored;
- the value may be in matching `"` or `'` quotes, and nothing inside them is interpreted;
- no `export`, no `${OTHER}`, no comment after a value, no key twice;
- only the keys in the template: a misspelt key is an error, not a secret silently ignored;
- an empty value means "not given".

A variable set in your shell wins over the file. `DISCORD_WEBHOOK_URL=… uv run tyche notify test` checks another webhook without editing anything.

`tyche init` creates `.env` readable by you only. If `tyche config check` warns that other users can read it, run the `chmod 600` command it prints.

## What is sent, and when

| Alert | When | Sent by |
|---|---|---|
| Kill switch engaged | `tyche kill`, when it engages the switch or adds flatten | the command, at once |
| Trading resumed | `tyche resume` lifts the switch, the drawdown halt, or both | the command, at once |
| Drawdown kill: trading is halted | the drawdown kill triggers at a close | paper and live runs, from Phase 2 PR 14 |
| Daily loss limit reached | a session loses at least the profile's limit | paper and live runs, from PR 14 |
| Kill switch engaged at a decision | a run finds the switch engaged (once per run) | paper and live runs, from PR 14 |
| Market data problems | the audit found problems in the data a run used (one message, the first ten listed) | paper and live runs, from PR 14 |
| A run failed | a run stopped with an error | paper and live runs, from PR 14 |
| Test | `tyche notify test` | the command |

**Never sent:** backtests, walk-forwards, sweeps, `tyche capital` and `tyche compare-profiles` post nothing. Routine risk cuts (a position shrunk to its size limit, an entry blocked by the position count, a purchase cut to the money caps) are not alerts; they happen at almost every close and belong in the daily summary, which comes later in Phase 2.

Times in alerts are in UTC. Reconciliation, the scheduler and the gateway add their own alerts when they are built.

**A failure to notify never stops anything.** If Discord cannot be reached, or the webhook was deleted, the command still does its job, prints why the alert was not sent, and logs it. After Discord refuses a webhook (HTTP 401, 403 or 404), Tyche stops using it until it restarts, as Discord asks; make a new webhook and update `.env`.

## Logs

Every command run on a workspace writes to `logs/<date>.jsonl` there, one file per day (the date is in UTC). Each line is one JSON object:

```json
{"at": "2026-11-23T21:04:05.120Z", "level": "WARNING", "logger": "tyche.cli", "message": "kill switch engaged", "reason": "market chaos", "flatten": false}
```

- `logs/` is gitignored, readable by you only, and never deleted by Tyche.
- Every secret in `.env`, and anything that looks like a Discord webhook URL, is replaced by `[redacted]` before a line is written.
- To read one day: `cat logs/2026-11-23.jsonl`. To pick out problems, with `jq` installed: `jq 'select(.level != "INFO")' logs/*.jsonl`.

## If it did not work

| You see | What to do |
|---|---|
| `DISCORD_WEBHOOK_URL is not a Discord webhook URL` | The value is not of the form `https://discord.com/api/webhooks/<id>/<token>`. Copy it again from Discord's channel settings. |
| `unknown key …` | A key in `.env` is misspelt, or is not one Tyche reads. Compare with `.env.example` in the repository. |
| `Discord refused the webhook (HTTP 404)` | The webhook was deleted, or the URL is wrong. Make a new one and update `.env`. |
| `cannot reach Discord: …` | No network, or Discord is down. The command itself worked; the log has the alert. |
| `Discord asked Tyche to wait … more than 30 s` | Discord's rate limit. Try again in a minute. |

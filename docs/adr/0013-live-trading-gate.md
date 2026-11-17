# ADR-0013: The live-trading gate

- **Status:** Proposed
- **Date:** 2026-11-16

## Context

The brief is explicit: live trading is never turned on by code or by an agent. Only Pablo can switch to live, through a documented, deliberate manual step. Tyche is also developed with an AI agent that can run shell commands in the repository, so "the code does not do it" is not enough. The gate has to hold against a mistaken command as well.

## Decision

Live trading requires **all** of the following. Each is checked at startup of a live run, and any failure stops the run.

1. **No config or environment switch selects live.** Mode is an explicit argument to the run command. The default is paper. `.env.example` has no mode variable.
2. **An arming record created by hand.** `tyche live arm` is interactive: it refuses to run without a terminal, shows what would go live (strategies, risk profile, capital limit, account), and requires Pablo to type the live account id and a confirmation phrase. The record lives in the workspace's `state/` folder, expires after a set number of days, and is destroyed by any halt.
3. **Account identity check.** The broker adapter compares the connected account id with the one configured for the mode. The paper adapter refuses a live account and the live adapter refuses anything except the armed account.
4. **Strategy lifecycle.** Only strategies in the `live` state run in live mode, and reaching that state needs Pablo's recorded approval.
5. **Guardrails.** The capital and order-size limits in `guardrails.toml` apply regardless of what the account holds.
6. **Announcement.** Arming, disarming and every live start are logged and sent to Discord.

Protections against the AI pair specifically:

- `CLAUDE.md` lists "never enable live" among the never-do rules.
- When the arming command exists (Phase 2), a Claude Code permission rule will deny it, so an agent session cannot run it even if asked.
- No automated test touches a live account. The live adapter's tests run against a fake.

Going live is a runbook Pablo follows, not a phase of the roadmap.

## Alternatives considered

- **A `TYCHE_MODE=live` variable.** One edited line, or one copied `.env`, away from trading real money.
- **A config flag plus a confirmation prompt.** Better, but a prompt can be answered by a script.
- **A separate code branch or build for live.** Breaks backtest, paper and live parity.

## Consequences

- Going live takes several deliberate steps and cannot happen as a side effect of something else.
- An expired or destroyed arming record means live trading stops until Pablo re-arms. That is the intended failure direction.
- The exact command names, expiry period and confirmation wording are settled in Phase 2 with the runbook.

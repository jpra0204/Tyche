# ADR-0010: TOML config validated by pydantic; layered risk limits

- **Status:** Proposed
- **Date:** 2026-11-16

## Context

The brief requires typed, validated config: invalid config means the system refuses to start. Risk settings are named profiles; hard guardrails sit in a separate file that no profile can exceed; per-strategy overrides may only be stricter than the active profile. Strategy parameters live in versioned config, not in code.

## Decision

**Format: TOML.** Config files are TOML, read with the standard library's `tomllib`.

**Validation: pydantic.** Each file is parsed into a pydantic model that is frozen and forbids unknown keys, so a typo in a key name is an error instead of a silently ignored setting. Models live beside the code they configure; `tyche.config` does the file loading.

**Three layers of risk limits**, checked at startup in this order:

1. `config/guardrails.toml`: absolute limits. Only Pablo edits it.
2. `config/risk/<name>.toml`: one file per named profile. Every value must be within the guardrails.
3. Strategy overrides in `config/strategies/<name>.toml`: every value must be at least as strict as the active profile.

A violation at any layer stops startup with a message naming the file, the key, the value and the limit it broke.

**The active profile is chosen per run** (`--risk-profile` for backtests). For paper and live it is stored in the database and changed only by a manual CLI command that is logged and announced.

**Every run records a hash of its fully resolved config.**

Illustrative shape only; the real schema is designed with the risk layer in Phase 2:

```toml
# config/risk/default.toml
risk_per_trade      = "1%"    # of equity, applies to targets that carry a stop
max_open_positions  = 5
max_position_size   = "20%"   # of equity
daily_loss_limit    = "3%"    # then no new entries for the rest of the session
drawdown_kill       = "15%"   # from peak equity, then halt until manual restart
```

```toml
# config/guardrails.toml
allow_leverage      = false
allow_short         = false
max_total_capital   = { amount = "1000", currency = "CAD" }
max_order_value     = { amount = "250",  currency = "CAD" }
max_position_size   = "25%"
```

## Alternatives considered

- **YAML.** Familiar, but it needs a dependency and guesses types (`no` becomes false, `1e3` becomes a number), which is a poor fit for a file that sets money limits.
- **JSON.** No comments, and config needs comments.
- **Python files as config.** Maximum flexibility, and config that can execute code.
- **Environment variables for everything.** Fine for secrets and paths, unreadable for structured settings. `.env` is kept for secrets only.

## Consequences

- Config errors are caught at startup, before any order logic runs.
- The standard library reads TOML but does not write it. The improvement loop will need to write candidate config files in Phase 3; a small writer dependency will be chosen then.
- "Stricter" must be defined per field (a lower maximum is stricter, a higher minimum is stricter). Each field on the profile model will declare its direction, and property-based tests will check the ordering.

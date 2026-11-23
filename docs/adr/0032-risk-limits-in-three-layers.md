# ADR-0032: Risk limits in three layers: guardrail ceilings, named profiles, stricter strategy limits

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-23

## Context

[ADR-0010](0010-config-toml-pydantic.md) decided three layers of risk limits (guardrails, named profiles, per-strategy overrides), each checked against the one above when Tyche starts, and showed the files' shape as an illustration only: "the real schema is designed with the risk layer in Phase 2". Phase 2, PR 1 designs it. Nothing applies the limits to trades in this PR: the gate applies the position rules from PR 2, an order-level check comes in PR 3, and the account rules in PR 4.

Three questions came up, and Pablo answered each on 2026-11-23, before any code:

1. **What do the guardrails hold?** ADR-0010's sketch had only account limits (no leverage, no short, a capital cap, an order-value cap) and a position-size ceiling. A profile could then still set its daily loss limit or its drawdown kill to 100%, which switches that protection off. Pablo chose **a ceiling for every profile limit**.
2. **In what currency are the money caps?** The brief caps live capital in CAD, but the `US` profile holds only USD, and Tyche has no exchange rates until Phase 4. Pablo chose **one cap per cash currency**, over CAD caps with a fixed, dated exchange rate that would go stale.
3. **What may a strategy override?** The daily loss limit and the drawdown kill are measured on the whole account, so a per-strategy version would be a different rule. Pablo chose **position rules only**.

## Decision

**Three files, three layers.** Each is a frozen pydantic schema that rejects unknown keys (ADR-0010), converted to domain objects in `tyche.core.risk` (ADR-0017). Fractions are of account equity and written as decimal strings, as everywhere else in the config: `"0.20"` is 20%.

1. **`config/guardrails.toml`, the hard limits.** Only Pablo edits it.
   - `long_only = true` and `allow_leverage = false`. They are the only values accepted: they state what Tyche can do (brief §2), so that changing it one day is a deliberate edit of this file and of the code together.
   - A ceiling for every profile limit: `max_risk_per_trade`, `max_open_positions`, `max_position_size`, `max_daily_loss_limit`, `max_drawdown_kill`.
   - `max_total_capital` and `max_order_value`, each a list of `{ amount, currency }`, one per currency. Every cash currency of the active market profile needs both caps, or Tyche refuses to start. Each order cap is at most the capital cap in its currency. A CAD total across currencies can be added in Phase 4, when conversion exists.
2. **`config/risk/<name>.toml`, the named profiles.** The file name is the profile's name: lower-case letters, digits, `_` or `-`, starting with a letter (`default`, `test-a`, `safecash`), checked before it becomes a path. Five keys: `risk_per_trade`, `max_open_positions`, `max_position_size`, `daily_loss_limit`, `drawdown_kill`.
3. **`[risk]` in `config/strategies/<id>.toml`, a strategy's own limits.** Optional, and so is each of its three keys: `risk_per_trade`, `max_position_size` (of account equity, like the profile's) and `max_open_positions` (in that strategy's sleeve). A key not given takes the profile's value.

**Each value must be valid on its own.** Fractions are above 0; the daily loss limit and the drawdown kill are below 1, because a limit of 100% could never trigger; risk per trade and position size are at most 1. Counts are whole numbers of at least 1.

**Each layer is checked against the one above, at startup.** A value equal to its limit is allowed. Every breach in a file is reported at once, naming the file, the key, its value, and the limit with its key, for example:

```text
config/risk/default.toml: a risk profile may not exceed the guardrails (config/guardrails.toml)
  max_position_size = 0.30 is above max_position_size = 0.25
```

- **Every** profile in `config/risk/` is checked against the guardrails, whichever is active, so that switching to any of them later cannot fail on a limit.
- Strategy limits are checked against the **active** profile, as ADR-0010 says: a strategy limit looser than the active profile stops Tyche, it is not quietly lowered.

**The active profile** is `default` unless a run chooses another. `tyche config check --risk-profile <name>` checks against a chosen one and prints it, with the other valid profiles, the guardrails and each strategy's own limits. The config hash and every run record's snapshot cover the guardrails and the active profile only: editing a profile a run did not use does not change that run's hash.

**`tyche init` ships** `config/guardrails.toml` and `config/risk/default.toml`, with the brief's `default` profile (1% risk per trade, 5 positions, 20% per position, 3% daily loss limit, 15% drawdown kill) and example guardrails (2%, 10 positions, 25%, 5%, 25%; USD 700 of capital and USD 350 per order). The template values are a starting point for a scratch workspace. The values in Pablo's own workspace are his to set.

## Alternatives considered

- **Guardrails with account limits only, as sketched in ADR-0010.** Fewer keys, but a profile could disable the daily loss limit or the drawdown kill by setting it to 100%. Rejected by Pablo.
- **Money caps in CAD with a fixed, dated USD/CAD rate in the guardrails file.** Matches the brief's wording, but the rate goes stale and, if it is set wrongly, the cap is wrong in the unsafe direction. Rejected by Pablo; currency conversion arrives in Phase 4 with its own policy.
- **Every profile limit overridable per strategy.** A per-strategy daily loss limit or drawdown kill would be measured on a sleeve, which is a different rule with more for the gate to apply. Rejected by Pablo.
- **Strategy limits clamped to the active profile instead of refused.** Never looser by construction, so no failure. But ADR-0010 says a violation stops startup, and a limit that silently means something else than it says is harder to trust. Kept as ADR-0010 has it; PR 5 may revisit it (below).
- **Percent strings such as `"1%"`, as in ADR-0010's illustration.** Every other fraction in the config is a decimal string; a second notation is a second way to be wrong.
- **Hashing every profile.** Simpler, but then adding or editing a profile no run uses would change every run's hash and make identical runs look different.
- **`--risk-profile` on the backtest commands now, as the Phase 2 plan has it for PR 1.** Until the gate applies a profile (PR 2), a run record naming a profile would claim limits that were never applied. The flag moves to PR 2, where it first changes a result.

## Consequences

- An existing workspace stops starting until `config/guardrails.toml` and `config/risk/default.toml` are copied into it from a scratch workspace. That is intended: Tyche refuses to start without its hard limits. The [troubleshooting](../user-guide/07-troubleshooting.md#upgrading-a-workspace-created-by-an-older-tyche) table lists them.
- Every workspace's config hash changes once, because two files are now part of it. Trial counting is not affected: a trial is identified by plugin, version and parameters (ADR-0030), and a strategy's `[risk]` table is not a parameter.
- Nothing is enforced on trades yet. `tyche config check` says so. PR 2 applies the position rules in the gate, PR 3 checks every order against the guardrails (where the money caps apply in backtests is decided there), PR 4 the daily loss limit and the drawdown kill.
- A strategy limit that is stricter than `default` but looser than a stricter profile makes that profile unusable with that strategy. PR 5, which compares profiles side by side, will meet this first.
- The small-account profile proposed by [ADR-0031](0031-minimum-viable-capital.md) (one or two positions below about USD 5,000) needs a position size above the example guardrails' 25%. Choosing it in PR 5 means Pablo raises his own guardrail first.
- Shorting or leverage, if ever wanted, needs this schema to accept the other value: a code change, reviewed, not a config edit.

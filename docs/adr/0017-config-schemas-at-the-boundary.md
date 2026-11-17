# ADR-0017: Config file schemas live in `tyche.config`; the core receives domain objects

- **Status:** Proposed
- **Date:** 2026-11-17
- **Refines:** [ADR-0010](0010-config-toml-pydantic.md), the line "Models live beside the code they configure"

## Context

ADR-0010 chose TOML files validated by pydantic, and said the pydantic models would live beside the code they configure. Building the first real config in PR 4 showed a cost: the first models configure market profiles, which the core uses. Placing them beside that code puts pydantic inside `tyche.core`.

The core's value objects (`Money`, `Instrument`, `Bar`, `Session`) are frozen dataclasses that check their own rules (see the [value objects](../learning/value-objects.md) note). A pydantic model in the core would be a second way of doing the same job, with a third-party library at the centre of the system.

There is also a type question. TOML gives plain strings and lists. pydantic's fully strict mode rejects those for enum and tuple fields, while its default lax mode silently converts `"1"`, `true` and `1.0` into the integer `1`.

## Decision

1. **File schemas live in `tyche.config`.** Each config file has a pydantic model there that describes only its shape: which keys exist and what type each value has. Models are frozen and forbid unknown keys.
2. **Domain rules live in the domain object.** A schema converts itself to a core object (for example `MarketProfileFile.to_domain()` returns a `MarketProfile`), and that object's own checks enforce what makes a value meaningful. The rule is written once.
3. **The core never imports pydantic.** It receives domain objects only.
4. **Scalars are strict, containers are not.** Models run in pydantic's lax mode, but integer and string fields use `StrictInt` and `StrictStr`, so no value changes type on the way in. Enums and lists still accept the strings and arrays TOML produces.
5. **Errors name the file and the key**, and every problem in a file is reported at once.

## Alternatives considered

- **Models beside the code, as ADR-0010 said.** Puts pydantic in the core and creates two styles of value object.
- **Pydantic for the domain objects too.** One style, but the core would depend on a validation library for its most basic types, and immutable dataclasses already do the job.
- **Fully strict pydantic.** Rejects valid TOML for enums and lists, unless config is converted to JSON first, which adds a step that hides type information.
- **Default lax pydantic.** Accepts `schema_version = "1"` and `true` as `1` without complaint.

## Consequences

- Each config concept has two small classes: a file schema and a domain object. That duplication is the price of keeping pydantic out of the core, and it stays small because the schema only lists fields.
- A config error can come from either layer. Both are reported as `ConfigError` with the file name, so the user sees one kind of message.
- Later config (risk profiles, guardrails, strategies) follows the same pattern: schema in `tyche.config`, rules in the domain object.
- ADR-0010's "stricter than" checks between guardrails, risk profiles and strategy overrides are domain rules, so in Phase 2 they belong in the risk domain objects, not in the schemas.

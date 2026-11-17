# ADR-0007: LLMs out of the trading path; Python-driven agents

- **Status:** Accepted (brief for the LLM role; Pablo, 2026-11-16 for who drives)
- **Date:** 2026-11-16

## Context

The brief fixes the role of LLMs: research, review and proposals only. No LLM places an order or decides a trade at runtime.

It left open who drives an agent run. The brief says agents run "through Claude Code" as commands, and also that any step must be movable to a local model or the API through config. Those pull in different directions. If a Claude Code prompt *is* the agent (exploring files and calling tools as it sees fit), the workflow lives in the prompt and no other model can run it.

## Decision

1. **The trading path contains no LLM code.** An import-linter contract fails CI if `tyche.core.pipeline`, `risk`, `engine`, `sim` or `tyche.strategies` import `tyche.core.agents` or `tyche.adapters.llm`.
2. **Python drives every agent.** An agent is a workflow in `tyche.core.agents`: gather a read-only input bundle, build the prompt, call the `LLMProvider` port once, validate the JSON reply against a schema, write a file to the workspace.
3. **The LLM is a function behind a port.** `LLMProvider.complete(request)` takes prompts and a JSON Schema and returns JSON. The default adapter, `claude-code`, runs headless `claude -p` as a subprocess, which uses the existing Claude plan at no extra cost. `ollama` and `anthropic-api` adapters can be added later and selected per agent in config.
4. **Slash commands are thin wrappers.** `/weekly-review` runs `tyche agent review` and then helps Pablo read the result.
5. **Agent output is data with no authority.** Proposals pass schema validation, the automated gate and Pablo's approval before anything changes. Agents never see broker credentials and cannot edit risk config or guardrails.

## Alternatives considered

- **Claude Code drives.** The slash-command prompt is the agent. More capable at open-ended exploration, but not testable, not reproducible and not portable to another model.
- **Hybrid.** Python-driven reviewer and proposer, Claude-driven research analyst. Two patterns to learn and maintain. It can be revisited for the research analyst if a single call proves too limiting.

## Consequences

- Agent workflows are unit-testable with a fake `LLMProvider` that returns canned JSON.
- Each run is reproducible up to the model call: the input bundle is hashed and stored with the output.
- A single call cannot go and look for more information. Each agent's input bundle must be designed to contain what it needs, which is a real design task in Phase 3.
- The `claude -p` interface, its flags and its plan limits will be checked against current documentation in Phase 3 before the adapter is written.
- Details are in [agent architecture](../architecture/agent-architecture.md).

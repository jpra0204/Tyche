"""Offline LLM-agent workflows, driven by Python (ADR-0007).

Planned (Phase 3): for each agent, assemble a read-only input bundle, build the
prompt, call the ``LLMProvider`` port, validate the reply against a JSON Schema and
write the result to the workspace. Nothing here can be imported by the trading path;
CI enforces it.
"""

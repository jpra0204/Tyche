"""The pipeline stages from brief section 4.2, one subpackage per stage.

Each stage subscribes to its input event(s) and publishes its output event(s); stages
never call each other directly. The risk stage lives in ``tyche.core.risk`` because it
is more than a stage (profiles, guardrails, halts).
"""

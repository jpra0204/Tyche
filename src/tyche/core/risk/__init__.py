"""The risk layer (pipeline stage 5): an independent gate nothing can bypass.

Available now:

* ``PassThroughGate``, which approves every proposed portfolio unchanged, so the event
  flow is already the final one (Phase 1).
* The limits, in three layers (ADR-0032): ``Guardrails`` (absolute ceilings),
  ``RiskProfile`` (a named set of limits chosen per run) and ``StrategyRiskLimits``
  (per-strategy position limits that may only be stricter). Each layer checks the one
  below it and reports every ``LimitBreach`` at once. Nothing applies them yet.

Planned (Phase 2): the rules inside the gate (risk per trade, position caps, then the
daily loss limit and the drawdown kill switch) and halts.
"""

from tyche.core.risk.gate import PASS_THROUGH, PassThroughGate
from tyche.core.risk.limits import (
    DEFAULT_RISK_PROFILE,
    Guardrails,
    LimitBreach,
    RiskProfile,
    StrategyRiskLimits,
    require_risk_profile_name,
)

__all__ = [
    "DEFAULT_RISK_PROFILE",
    "PASS_THROUGH",
    "Guardrails",
    "LimitBreach",
    "PassThroughGate",
    "RiskProfile",
    "StrategyRiskLimits",
    "require_risk_profile_name",
]

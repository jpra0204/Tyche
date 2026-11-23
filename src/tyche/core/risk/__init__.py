"""The risk layer (pipeline stage 5): an independent gate nothing can bypass.

Available now:

* The limits, in three layers (ADR-0032): ``Guardrails`` (absolute ceilings),
  ``RiskProfile`` (a named set of limits chosen per run) and ``StrategyRiskLimits``
  (per-strategy position limits that may only be stricter). Each layer checks the one
  below it and reports every ``LimitBreach`` at once. ``RiskLimits`` bundles the three
  for one run and gives each strategy its ``StrategyLimits``.
* ``RiskGate``, which applies the position rules to every proposed portfolio: risk per
  trade, max position size and max open positions (ADR-0033). Its rules are the pure
  function ``review``, and it reads holdings through the ``Holdings`` protocol.
* The account rules (ADR-0015, ADR-0035): ``AccountRules`` measures equity at every
  close; the daily loss limit blocks entries and additions at that close, and the
  drawdown kill halts trading for the rest of the run. ``tyche resume`` lifts a halt
  (``AccountRulesState.resumed``, ADR-0039).
* The kill switch (ADR-0039): the gate reads a ``KillSwitch`` at every decision and,
  while it is engaged, approves nothing, carrying it on the approval.
"""

from tyche.core.risk.account import AccountRules
from tyche.core.risk.gate import (
    WEIGHT_PLACES,
    Holdings,
    Review,
    RiskGate,
    RiskGateError,
    review,
)
from tyche.core.risk.limits import (
    DEFAULT_RISK_PROFILE,
    Guardrails,
    LimitBreach,
    RiskLimits,
    RiskProfile,
    StrategyLimits,
    StrategyRiskLimits,
    require_risk_profile_name,
)

__all__ = [
    "DEFAULT_RISK_PROFILE",
    "WEIGHT_PLACES",
    "AccountRules",
    "Guardrails",
    "Holdings",
    "LimitBreach",
    "Review",
    "RiskGate",
    "RiskGateError",
    "RiskLimits",
    "RiskProfile",
    "StrategyLimits",
    "StrategyRiskLimits",
    "require_risk_profile_name",
    "review",
]

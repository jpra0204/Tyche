"""Risk limits for tests.

``UNBOUND`` is a test profile whose limits never bind for the example strategies:
risk per trade of 100% (no stop can lose more than the whole position), a position
may be all of equity, and more open positions than any test holds. The golden-file and
reference tests run under it, so the risk gate approves their trades unchanged and
their expected results stay those of the code they were checked against (ADR-0033).

``DEFAULT`` holds the values of the ``default`` profile that ``tyche init`` writes,
within the template guardrails.
"""

from decimal import Decimal

from tyche.core.domain import Currency, Money
from tyche.core.risk import Guardrails, RiskLimits, RiskProfile


def guardrails(
    *,
    risk_per_trade: str = "1",
    open_positions: int = 1000,
    position_size: str = "1",
) -> Guardrails:
    return Guardrails(
        max_risk_per_trade=Decimal(risk_per_trade),
        max_open_positions=open_positions,
        max_position_size=Decimal(position_size),
        max_daily_loss_limit=Decimal("0.99"),
        max_drawdown_kill=Decimal("0.99"),
        max_total_capital=(Money.of("1000000000", Currency.USD),),
        max_order_value=(Money.of("1000000000", Currency.USD),),
    )


def profile(
    name: str = "test",
    *,
    risk_per_trade: str = "1",
    open_positions: int = 1000,
    position_size: str = "1",
) -> RiskProfile:
    return RiskProfile(
        name=name,
        risk_per_trade=Decimal(risk_per_trade),
        max_open_positions=open_positions,
        max_position_size=Decimal(position_size),
        daily_loss_limit=Decimal("0.5"),
        drawdown_kill=Decimal("0.5"),
    )


UNBOUND = RiskLimits(guardrails(), profile("unbound"))

DEFAULT = RiskLimits(
    guardrails(risk_per_trade="0.02", open_positions=10, position_size="0.25"),
    RiskProfile(
        name="default",
        risk_per_trade=Decimal("0.01"),
        max_open_positions=5,
        max_position_size=Decimal("0.20"),
        daily_loss_limit=Decimal("0.03"),
        drawdown_kill=Decimal("0.15"),
    ),
)

"""Trading costs for tests: IBKR Pro Fixed for US stocks, as checked on 2026-11-17.

The same rates as the packaged ``config/costs/US.toml`` template; a loader test checks
that the two agree, so neither can drift without a test failing.
"""

from datetime import date
from decimal import Decimal

from tyche.core.domain import CommissionSchedule, Currency, Money, RegulatoryFees, TradingCosts


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


US_COSTS = TradingCosts(
    commission=CommissionSchedule(
        per_share=usd("0.005"), minimum=usd("1.00"), maximum_rate=Decimal("0.01")
    ),
    regulatory_fees=RegulatoryFees(
        sec_fee_rate=Decimal("0.0000206"),
        taf_per_share_sold=usd("0"),
        cat_per_share=usd("0.000003"),
    ),
    slippage_bps=Decimal(5),
    settlement_days=1,
    checked_on=date(2026, 11, 17),
)

NO_FEES = RegulatoryFees(
    sec_fee_rate=Decimal(0), taf_per_share_sold=usd("0"), cat_per_share=usd("0")
)

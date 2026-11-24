"""Trading costs for tests: IBKR Pro Fixed and Tiered for US stocks, as checked.

The same rates as the packaged ``config/costs/US.toml`` template (Fixed checked on
2026-11-17, Tiered re-checked on 2026-11-22 with Fixed unchanged); a loader test checks
that the two agree, so neither can drift without a test failing.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from tyche.core.domain import (
    CommissionSchedule,
    Currency,
    Money,
    RegulatoryFees,
    TieredSchedule,
    TradingCosts,
)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


US_COSTS = TradingCosts(
    commission=CommissionSchedule(
        per_share=usd("0.005"), minimum=usd("1.00"), maximum_rate=Decimal("0.01")
    ),
    regulatory_fees=RegulatoryFees(
        sec_fee_rate=Decimal("0.0000206"),
        taf_per_share_sold=usd("0.000195"),
        cat_per_share=usd("0.000003"),
    ),
    slippage_bps=Decimal(5),
    settlement_days=1,
    checked_on=date(2026, 11, 17),
)

NO_FEES = RegulatoryFees(
    sec_fee_rate=Decimal(0), taf_per_share_sold=usd("0"), cat_per_share=usd("0")
)

TIERED = TieredSchedule(
    per_share=usd("0.0035"),
    minimum=usd("0.35"),
    maximum_rate=Decimal("0.01"),
    clearing_per_share=usd("0.0002"),
    clearing_maximum_rate=Decimal("0.005"),
    nyse_pass_through_rate=Decimal("0.000175"),
    finra_pass_through_rate=Decimal("0.000563"),
    exchange_fee_per_share=usd("0.0030"),
)

US_TIERED_COSTS = replace(US_COSTS, commission=TIERED)

"""Market profiles for tests: the packaged ``US`` profile and a Canadian one.

``US_TEMPLATE_PROFILE`` matches the packaged ``config/markets/US.toml`` template; a
loader test checks that the two agree, so neither can drift without a test failing.

``US_PROFILE`` is the same profile with only two candidates, SPY and QQQ, so that a
test replaying it needs made-up data for two instruments, not nine.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from tyche.core.domain import (
    AssetClass,
    Currency,
    DailyCycleRules,
    ExecutionRules,
    Instrument,
    MarketProfile,
    Money,
    ReconciliationRules,
    UniverseRules,
)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


US_RULES = UniverseRules(
    asset_classes=(AssetClass.STOCK, AssetClass.ETF),
    min_price=usd("5.00"),
    min_average_dollar_volume=usd("10000000"),
    liquidity_sessions=20,
    quality_sessions=5,
    instruments=(
        Instrument("SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF),
        Instrument("QQQ", "XNAS", Currency.USD, "XNYS", AssetClass.ETF),
    ),
)

US_EXECUTION = ExecutionRules(rebalance_band=Decimal("0.10"), price_buffer=Decimal("0.02"))

US_BENCHMARK = Instrument("SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)

US_DAILY_CYCLE = DailyCycleRules(
    after_close=timedelta(minutes=120), before_next_open=timedelta(minutes=30)
)

US_RECONCILIATION = ReconciliationRules(cash_tolerance=Decimal("1.00"))
US_PROFILE = MarketProfile(
    "US",
    (Currency.USD,),
    ("XNYS",),
    US_RULES,
    US_EXECUTION,
    US_BENCHMARK,
    US_DAILY_CYCLE,
    US_RECONCILIATION,
)


def _etf(symbol: str, exchange: str) -> Instrument:
    return Instrument(symbol, exchange, Currency.USD, "XNYS", AssetClass.ETF)


US_TEMPLATE_PROFILE = replace(
    US_PROFILE,
    universe=replace(
        US_RULES,
        instruments=(
            _etf("SPY", "ARCX"),
            _etf("QQQ", "XNAS"),
            _etf("IWM", "ARCX"),
            _etf("EFA", "ARCX"),
            _etf("EEM", "ARCX"),
            _etf("TLT", "XNAS"),
            _etf("IEF", "XNAS"),
            _etf("GLD", "ARCX"),
            _etf("VNQ", "ARCX"),
        ),
    ),
)

CA_RULES = replace(
    US_RULES,
    min_price=Money.of("5.00", Currency.CAD),
    min_average_dollar_volume=Money.of("10000000", Currency.CAD),
    instruments=(),
)

CA_BENCHMARK = Instrument("XIC", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)

CA_PROFILE = MarketProfile(
    "CA",
    (Currency.CAD,),
    ("XTSE",),
    CA_RULES,
    US_EXECUTION,
    CA_BENCHMARK,
    US_DAILY_CYCLE,
    US_RECONCILIATION,
)

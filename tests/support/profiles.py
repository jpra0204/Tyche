"""Market profiles for tests: the packaged ``US`` profile and a Canadian one.

``US_PROFILE`` matches the packaged ``config/markets/US.toml`` template; a loader test
checks that the two agree, so neither can drift without a test failing.
"""

from dataclasses import replace

from tyche.core.domain import AssetClass, Currency, MarketProfile, Money, UniverseRules


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


US_RULES = UniverseRules(
    asset_classes=(AssetClass.STOCK, AssetClass.ETF),
    min_price=usd("5.00"),
    min_average_dollar_volume=usd("10000000"),
    liquidity_sessions=20,
    quality_sessions=5,
)

US_PROFILE = MarketProfile("US", (Currency.USD,), ("XNYS",), US_RULES)

CA_RULES = replace(
    US_RULES,
    min_price=Money.of("5.00", Currency.CAD),
    min_average_dollar_volume=Money.of("10000000", Currency.CAD),
)

CA_PROFILE = MarketProfile("CA", (Currency.CAD,), ("XTSE",), CA_RULES)

"""MarketProfile: a named set of markets, validated on creation."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from tests.support.profiles import (
    US_BENCHMARK,
    US_DAILY_CYCLE,
    US_EXECUTION,
    US_RECONCILIATION,
    US_RULES,
)
from tyche.core.domain import (
    AssetClass,
    Currency,
    Instrument,
    MarketProfile,
    Money,
    require_profile_name,
)

US = MarketProfile(
    name="US",
    cash_currencies=(Currency.USD,),
    calendars=("XNYS",),
    universe=US_RULES,
    execution=US_EXECUTION,
    benchmark=US_BENCHMARK,
    daily_cycle=US_DAILY_CYCLE,
    reconciliation=US_RECONCILIATION,
)


def test_holds_its_fields() -> None:
    assert US.name == "US"
    assert US.cash_currencies == (Currency.USD,)
    assert US.calendars == ("XNYS",)
    assert str(US) == "US"


def test_is_immutable() -> None:
    profile: Any = US
    with pytest.raises(FrozenInstanceError):
        profile.name = "CA"


def test_a_combined_profile_holds_both_currencies_and_calendars() -> None:
    both = MarketProfile(
        "CA+US",
        (Currency.CAD, Currency.USD),
        ("XTSE", "XNYS"),
        US_RULES,
        US_EXECUTION,
        US_BENCHMARK,
        US_DAILY_CYCLE,
        US_RECONCILIATION,
    )

    assert both.cash_currencies == (Currency.CAD, Currency.USD)
    assert both.calendars == ("XTSE", "XNYS")


@pytest.mark.parametrize("name", ["US", "CA", "CA+US", "ABC+DEF+GHI"])
def test_accepts_valid_names(name: str) -> None:
    require_profile_name(name)
    assert replace(US, name=name).name == name


@pytest.mark.parametrize(
    "name", ["", "us", "US ", "US+", "+US", "CA++US", "CA-US", "../US", "US/CA", "U1"]
)
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="invalid market profile name"):
        require_profile_name(name)
    with pytest.raises(ValueError, match="invalid market profile name"):
        replace(US, name=name)


def test_needs_a_cash_currency() -> None:
    with pytest.raises(ValueError, match="at least one cash currency"):
        replace(US, cash_currencies=())


def test_rejects_a_repeated_currency() -> None:
    with pytest.raises(ValueError, match="cash currencies are repeated"):
        replace(US, cash_currencies=(Currency.USD, Currency.USD))


def test_needs_a_calendar() -> None:
    with pytest.raises(ValueError, match="at least one calendar"):
        replace(US, calendars=())


def test_rejects_a_malformed_calendar() -> None:
    with pytest.raises(ValueError, match="invalid calendar"):
        replace(US, calendars=("NYSE ",))


def test_rejects_a_repeated_calendar() -> None:
    with pytest.raises(ValueError, match="calendars are repeated"):
        replace(US, calendars=("XNYS", "XNYS"))


def test_holds_its_universe_rules() -> None:
    assert US.universe == US_RULES
    assert US.universe.currency is Currency.USD


def test_universe_thresholds_must_be_in_a_cash_currency() -> None:
    in_cad = replace(
        US_RULES,
        min_price=Money.of("5", Currency.CAD),
        min_average_dollar_volume=Money.of("1", Currency.CAD),
        instruments=(),
    )

    with pytest.raises(ValueError, match="universe thresholds are in CAD"):
        replace(US, universe=in_cad)


def test_every_instrument_must_follow_one_of_the_profiles_calendars() -> None:
    on_nasdaq_calendar = Instrument("QQQ", "XNAS", Currency.USD, "XNAS", AssetClass.ETF)
    rules = replace(US_RULES, instruments=(on_nasdaq_calendar,))

    with pytest.raises(ValueError, match="QQQ@XNAS follows calendar XNAS, which is not one"):
        replace(US, universe=rules)


def test_holds_its_benchmark() -> None:
    assert US.benchmark == US_BENCHMARK


def test_the_benchmark_must_follow_one_of_its_calendars() -> None:
    tsx = Instrument("XIC", "XTSE", Currency.USD, "XTSE", AssetClass.ETF)

    with pytest.raises(ValueError, match="benchmark XIC@XTSE follows calendar XTSE"):
        replace(US, benchmark=tsx)


def test_the_benchmark_must_trade_in_one_of_its_cash_currencies() -> None:
    cad = Instrument("SPY", "ARCX", Currency.CAD, "XNYS", AssetClass.ETF)

    with pytest.raises(ValueError, match="benchmark SPY@ARCX trades in CAD"):
        replace(US, benchmark=cad)

"""MarketProfile: a named set of markets, validated on creation."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from tyche.core.domain import Currency, MarketProfile, require_profile_name

US = MarketProfile(name="US", cash_currencies=(Currency.USD,), calendars=("XNYS",))


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
    both = MarketProfile("CA+US", (Currency.CAD, Currency.USD), ("XTSE", "XNYS"))

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

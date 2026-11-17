"""Instrument carries its own currency, exchange and calendar, and validates them."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from tyche.core.domain import AssetClass, Currency, Instrument

SPY = Instrument(
    symbol="SPY",
    exchange="ARCX",
    currency=Currency.USD,
    calendar="XNYS",
    asset_class=AssetClass.ETF,
)


def test_carries_currency_exchange_and_calendar() -> None:
    assert SPY.currency is Currency.USD
    assert SPY.exchange == "ARCX"
    assert SPY.calendar == "XNYS"
    assert SPY.asset_class is AssetClass.ETF


def test_str_shows_symbol_and_exchange() -> None:
    assert str(SPY) == "SPY@ARCX"


def test_is_immutable() -> None:
    instrument: Any = SPY
    with pytest.raises(FrozenInstanceError):
        instrument.symbol = "QQQ"


def test_equal_fields_mean_the_same_instrument() -> None:
    twin = Instrument("SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
    assert twin == SPY
    assert hash(twin) == hash(SPY)
    assert len({SPY, twin}) == 1


def test_same_symbol_on_another_exchange_is_a_different_instrument() -> None:
    ry_new_york = Instrument("RY", "XNYS", Currency.USD, "XNYS", AssetClass.STOCK)
    ry_toronto = Instrument("RY", "XTSE", Currency.CAD, "XTSE", AssetClass.STOCK)
    assert ry_new_york != ry_toronto
    assert len({ry_new_york, ry_toronto}) == 2


@pytest.mark.parametrize("symbol", ["SPY", "BRK.B", "BRK-B", "A", "3M", "BF.A"])
def test_accepts_real_world_symbols(symbol: str) -> None:
    assert replace(SPY, symbol=symbol).symbol == symbol


@pytest.mark.parametrize(
    "symbol",
    ["", "spy", "SPY ", " SPY", "S PY", "SPY.", ".SPY", "BRK..B", "SPY$", "RY.to"],
)
def test_rejects_malformed_symbols(symbol: str) -> None:
    with pytest.raises(ValueError, match="invalid symbol"):
        replace(SPY, symbol=symbol)


@pytest.mark.parametrize("mic", ["", "NYSE ", "xnys", "XNY", "XNYSE", "X-YS"])
def test_rejects_malformed_exchange_and_calendar(mic: str) -> None:
    with pytest.raises(ValueError, match="invalid exchange"):
        replace(SPY, exchange=mic)
    with pytest.raises(ValueError, match="invalid calendar"):
        replace(SPY, calendar=mic)

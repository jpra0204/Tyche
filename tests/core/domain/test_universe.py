"""UniverseRules: the thresholds of a market profile, validated on creation."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from tests.support.market import SPY
from tests.support.profiles import US_RULES, usd
from tyche.core.domain import (
    DISQUALIFYING_ISSUES,
    AssetClass,
    Currency,
    DataIssueKind,
    Instrument,
    Money,
)

XIU = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)


def test_the_currency_is_the_thresholds_currency() -> None:
    assert US_RULES.currency is Currency.USD


def test_is_immutable() -> None:
    rules: Any = US_RULES
    with pytest.raises(FrozenInstanceError):
        rules.liquidity_sessions = 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"asset_classes": ()}, "at least one asset class"),
        ({"asset_classes": (AssetClass.ETF, AssetClass.ETF)}, "asset classes are repeated"),
        ({"min_price": Money.of("5", Currency.CAD)}, "must be in one currency"),
        ({"min_price": usd("0")}, "min_price must be positive"),
        ({"min_average_dollar_volume": usd("-1")}, "cannot be negative"),
        ({"liquidity_sessions": 0}, "liquidity_sessions must be at least 1"),
        ({"quality_sessions": 0}, "quality_sessions must be at least 1"),
        ({"instruments": (SPY, SPY)}, "instruments are repeated"),
        ({"instruments": (XIU,)}, "XIU@XTSE is quoted in CAD, but the thresholds are in USD"),
        (
            {"asset_classes": (AssetClass.STOCK,)},
            "SPY@ARCX is of asset class etf, which is not allowed",
        ),
    ],
)
def test_rejects_impossible_rules(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(US_RULES, **changes)


def test_issues_that_may_mean_a_wrong_or_absent_price_disqualify() -> None:
    assert (
        frozenset(
            {
                DataIssueKind.MISSING_SESSION,
                DataIssueKind.CONFLICT,
                DataIssueKind.INVALID_BAR,
                DataIssueKind.SUSPECT_MOVE,
            }
        )
        == DISQUALIFYING_ISSUES
    )

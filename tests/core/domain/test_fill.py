"""A fill knows its own cash flow and refuses impossible values."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from tests.support.ledger import fill
from tyche.core.domain import Currency, Money, Side


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def test_a_buy_costs_gross_plus_commission() -> None:
    bought = fill(Side.BUY, "10", "100.25", commission="1.05")

    assert bought.gross == usd("1002.50")
    assert bought.cash_flow == usd("-1003.55")


def test_a_sale_brings_in_gross_minus_commission() -> None:
    sold = fill(Side.SELL, "10", "100.25", commission="1.05")

    assert sold.cash_flow == usd("1001.45")


def test_fractional_shares_are_exact() -> None:
    assert fill(Side.BUY, "0.333", "300", commission="0").gross == usd("99.900")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"quantity": Decimal(0)}, "quantity must be positive"),
        ({"price": usd("0")}, "price must be positive"),
        (
            {"price": Money.of("100", Currency.CAD), "commission": Money.of("1", Currency.CAD)},
            "price is in CAD",
        ),
        ({"commission": usd("-1")}, "commission cannot be negative"),
        ({"commission": Money.of("1", Currency.CAD)}, "commission must be in the trade currency"),
        ({"fill_id": ""}, "needs a fill_id"),
    ],
)
def test_refuses_impossible_values(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(fill(Side.BUY, "10", "100"), **change)


def test_cannot_settle_before_it_trades() -> None:
    with pytest.raises(ValueError, match="settles before it trades"):
        fill(Side.BUY, "10", "100", settle_days=-1)

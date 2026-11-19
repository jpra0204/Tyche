"""The sleeve book: each strategy's own shares, entry, average price and resting stop."""

from datetime import date
from decimal import Decimal

import pytest

from tests.support.costs import usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import StrategyPosition
from tyche.core.pipeline.execution import RestingStop, SleeveBook, SleeveBookError

D = Decimal
MON, TUE = date(2024, 1, 8), date(2024, 1, 9)


def test_each_sleeve_sees_only_its_own_positions() -> None:
    book = SleeveBook()
    book.add("a", SPY, D(10), usd("100"), MON)
    book.add("b", SPY, D(5), usd("101"), TUE)
    book.add("a", QQQ, D(2), usd("400"), TUE)

    assert book.positions_of("a") == (
        StrategyPosition(QQQ, D(2), TUE, usd("400")),
        StrategyPosition(SPY, D(10), MON, usd("100")),
    )
    assert book.total(SPY) == 15
    assert book.holders(SPY) == ("a", "b")
    assert book.instruments == (QQQ, SPY)
    assert book.positions_of("c") == ()


def test_adding_keeps_the_entry_date_and_averages_the_price() -> None:
    book = SleeveBook()
    book.add("a", SPY, D(10), usd("100"), MON)
    book.add("a", SPY, D(10), usd("110"), TUE)

    [position] = book.positions_of("a")
    assert (position.quantity, position.entry_date, position.entry_price) == (
        D(20),
        MON,
        usd("105"),
    )


def test_removing_keeps_the_average_price_and_all_of_it_closes_the_holding() -> None:
    book = SleeveBook()
    book.add("a", SPY, D(3), usd("100"), MON)
    book.remove("a", SPY, D(1))

    [position] = book.positions_of("a")
    assert (position.quantity, position.entry_price) == (D(2), usd("100"))
    book.remove("a", SPY, D(2))
    assert book.held("a", SPY) == 0
    assert book.instruments == ()


def test_a_sleeve_cannot_give_up_shares_it_does_not_hold() -> None:
    book = SleeveBook()
    book.add("a", SPY, D(3), usd("100"), MON)

    with pytest.raises(SleeveBookError, match="holds 3"):
        book.remove("a", SPY, D(4))
    with pytest.raises(SleeveBookError, match="holds 0"):
        book.remove("b", SPY, D(1))


def test_the_resting_stop_shows_in_the_position() -> None:
    book = SleeveBook()
    book.add("a", SPY, D(3), usd("100"), MON)
    book.set_stop("a", SPY, RestingStop("stop-1", usd("95")))

    assert book.positions_of("a")[0].stop_price == usd("95")
    assert book.stops == (("a", SPY, RestingStop("stop-1", usd("95"))),)
    book.set_stop("a", SPY, None)
    assert book.positions_of("a")[0].stop_price is None


def test_refuses_nonsense_additions() -> None:
    book = SleeveBook()
    with pytest.raises(SleeveBookError, match="cannot add 0"):
        book.add("a", SPY, D(0), usd("100"), MON)
    with pytest.raises(SleeveBookError, match="at 0"):
        book.add("a", SPY, D(1), usd("0"), MON)

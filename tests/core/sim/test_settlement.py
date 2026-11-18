"""Settlement dates: T+n sessions on the real NYSE calendar."""

from datetime import date

import pytest

from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.sim import settlement_date

NYSE = ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))


@pytest.mark.parametrize(
    ("trade", "days", "settles"),
    [
        (date(2024, 1, 2), 1, date(2024, 1, 3)),  # Tuesday to Wednesday
        (date(2024, 1, 5), 1, date(2024, 1, 8)),  # Friday to Monday
        (date(2024, 1, 12), 1, date(2024, 1, 16)),  # over Martin Luther King Jr. Day
        (date(2024, 1, 12), 2, date(2024, 1, 17)),
        (date(2024, 1, 2), 0, date(2024, 1, 2)),
    ],
)
def test_settles_n_sessions_later(trade: date, days: int, settles: date) -> None:
    assert settlement_date(trade, days, NYSE) == settles


def test_refuses_a_trade_on_a_closed_day() -> None:
    with pytest.raises(ValueError, match="2024-01-15 is not a XNYS session"):
        settlement_date(date(2024, 1, 15), 1, NYSE)


def test_refuses_negative_days() -> None:
    with pytest.raises(ValueError, match="settlement_days must be zero or more"):
        settlement_date(date(2024, 1, 2), -1, NYSE)

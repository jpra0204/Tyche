"""Session: one trading day, with its opening and closing times in UTC."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from tyche.core.domain import Session

HALF_DAY = Session(
    calendar="XNYS",
    day=date(2024, 7, 3),
    opens_at=datetime(2024, 7, 3, 13, 30, tzinfo=UTC),
    closes_at=datetime(2024, 7, 3, 17, 0, tzinfo=UTC),
    is_half_day=True,
)


def test_holds_its_fields() -> None:
    assert HALF_DAY.calendar == "XNYS"
    assert HALF_DAY.day == date(2024, 7, 3)
    assert HALF_DAY.closes_at - HALF_DAY.opens_at == timedelta(hours=3, minutes=30)
    assert HALF_DAY.is_half_day


def test_str_names_the_calendar_and_the_day() -> None:
    assert str(HALF_DAY) == "XNYS session 2024-07-03"


def test_is_immutable_and_equal_by_value() -> None:
    session: Any = HALF_DAY
    with pytest.raises(FrozenInstanceError):
        session.is_half_day = False
    assert replace(HALF_DAY) == HALF_DAY


def test_rejects_a_malformed_calendar_code() -> None:
    with pytest.raises(ValueError, match="invalid calendar"):
        replace(HALF_DAY, calendar="NYSE ")


@pytest.mark.parametrize("field", ["opens_at", "closes_at"])
def test_rejects_times_that_are_not_utc(field: str) -> None:
    new_york = timezone(timedelta(hours=-4))
    local: dict[str, Any] = {field: datetime(2024, 7, 3, 12, 0, tzinfo=new_york)}
    with pytest.raises(ValueError, match=rf"{field} must be timezone-aware UTC"):
        replace(HALF_DAY, **local)


def test_rejects_a_session_that_closes_before_it_opens() -> None:
    with pytest.raises(ValueError, match="must open before it closes"):
        replace(HALF_DAY, opens_at=HALF_DAY.closes_at)

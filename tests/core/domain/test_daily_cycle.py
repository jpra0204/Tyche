"""DailyCycleRules: when a session's bars are final, and until when its decision trades."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.support.market import session
from tests.support.profiles import US_DAILY_CYCLE
from tyche.core.domain import DailyCycleRules


def test_bars_count_as_final_two_hours_after_the_close() -> None:
    friday = session(date(2024, 1, 12))

    assert US_DAILY_CYCLE.ready_at(friday) == datetime(2024, 1, 12, 23, 0, tzinfo=UTC)


def test_a_decision_trades_until_thirty_minutes_before_the_next_open() -> None:
    # Friday 12 January's decision: the next session is Tuesday 16 January (Martin
    # Luther King Jr. Day in between), which opens at 14:30 UTC.
    tuesday = session(date(2024, 1, 16))

    assert US_DAILY_CYCLE.trade_until(tuesday) == datetime(2024, 1, 16, 14, 0, tzinfo=UTC)


def test_zero_waits_are_allowed() -> None:
    rules = DailyCycleRules(after_close=timedelta(0), before_next_open=timedelta(0))
    day = session(date(2024, 1, 12))

    assert rules.ready_at(day) == day.closes_at
    assert rules.trade_until(day) == day.opens_at


@pytest.mark.parametrize("field", ["after_close", "before_next_open"])
def test_a_negative_wait_is_refused(field: str) -> None:
    values = {"after_close": timedelta(0), "before_next_open": timedelta(0)}
    values[field] = timedelta(minutes=-1)

    with pytest.raises(ValueError, match=field):
        DailyCycleRules(**values)

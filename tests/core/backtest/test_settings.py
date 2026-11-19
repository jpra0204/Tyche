"""Backtest settings: the starting cash, and a holdout no backtest may reach."""

from datetime import date

import pytest

from tests.support.costs import usd
from tyche.core.backtest import BacktestSettings, HoldoutError

SETTINGS = BacktestSettings(holdout_starts=date(2024, 1, 1), starting_cash=usd("10000"))


def test_a_run_ending_the_day_before_the_holdout_is_allowed() -> None:
    SETTINGS.require_before_holdout(date(2023, 12, 31))


@pytest.mark.parametrize("last", [date(2024, 1, 1), date(2025, 6, 30)])
def test_a_run_reaching_the_holdout_is_refused(last: date) -> None:
    with pytest.raises(HoldoutError, match="from 2024-01-01 on is the reserved holdout"):
        SETTINGS.require_before_holdout(last)


@pytest.mark.parametrize("cash", ["0", "-1"])
def test_the_starting_cash_must_be_positive(cash: str) -> None:
    with pytest.raises(ValueError, match="starting cash must be positive"):
        BacktestSettings(holdout_starts=date(2024, 1, 1), starting_cash=usd(cash))

"""Execution rules and plan lines check themselves (ADR-0023)."""

from decimal import Decimal

import pytest

from tests.support.market import SPY
from tyche.core.domain import ExecutionRules, PlanLine, PlanNote

D = Decimal


class TestExecutionRules:
    @pytest.mark.parametrize("field", ["rebalance_band", "price_buffer"])
    @pytest.mark.parametrize("value", ["-0.01", "1", "NaN"])
    def test_refuses_values_outside_zero_to_one(self, field: str, value: str) -> None:
        values = {"rebalance_band": D("0.1"), "price_buffer": D("0.02"), field: D(value)}

        with pytest.raises(ValueError, match=field):
            ExecutionRules(**values)

    def test_a_resize_inside_the_band_is_kept(self) -> None:
        rules = ExecutionRules(rebalance_band=D("0.10"), price_buffer=D(0))

        assert rules.within_band(D(95), D(100))
        assert rules.within_band(D(110), D(100))
        assert not rules.within_band(D(89), D(100))

    def test_entries_and_exits_are_never_inside_the_band(self) -> None:
        rules = ExecutionRules(rebalance_band=D("0.5"), price_buffer=D(0))

        assert not rules.within_band(D(0), D(1))
        assert not rules.within_band(D(1), D(0))

    def test_a_zero_band_keeps_only_an_exact_holding(self) -> None:
        rules = ExecutionRules(rebalance_band=D(0), price_buffer=D(0))

        assert rules.within_band(D(10), D(10))
        assert not rules.within_band(D(10), D(11))


class TestPlanLine:
    def test_held_crossed_and_ordered_add_up_to_the_target(self) -> None:
        line = PlanLine("a", SPY, held=D(4), target=D(10), crossed=D(2), ordered=D(4))

        assert line.planned == 10

    def test_a_plan_that_does_not_add_up_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must equal the target"):
            PlanLine("a", SPY, held=D(4), target=D(10), ordered=D(5))

    def test_a_cash_limited_plan_ends_below_its_target(self) -> None:
        PlanLine("a", SPY, D(0), D(10), ordered=D(7), note=PlanNote.CASH_LIMITED)

        with pytest.raises(ValueError, match="ends below its target"):
            PlanLine("a", SPY, D(0), D(10), ordered=D(10), note=PlanNote.CASH_LIMITED)

    def test_whole_shares_only_and_one_direction(self) -> None:
        with pytest.raises(ValueError, match="whole shares"):
            PlanLine("a", SPY, D("1.5"), D("1.5"))
        with pytest.raises(ValueError, match="opposite directions"):
            PlanLine("a", SPY, D(4), D(4), crossed=D(2), ordered=D(-2))
        with pytest.raises(ValueError, match="cannot be negative"):
            PlanLine("a", SPY, D(-1), D(0), ordered=D(1))

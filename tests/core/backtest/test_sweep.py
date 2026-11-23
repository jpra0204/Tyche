"""Parameter sweeps: the grid, the pick, the deflated Sharpe ratio and the warnings.

The deflated Sharpe ratio is checked against the worked example in Bailey and López de
Prado (2014): N = 100 trials, an annualised variance of Sharpe ratios of 1/2, T = 1250
daily returns, an annualised Sharpe ratio of 2.5, skewness -3 and kurtosis 10, with
250 observations a year. The paper gives SR0 = 0.1132 per observation and a deflated
Sharpe ratio of 0.9004, and 0.9505 had the strategist run 46 trials.
"""

import math
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.support.market import JANUARY_2024, SPY, bar, close_of
from tyche.core.backtest import (
    BacktestMetrics,
    EquityPoint,
    Grid,
    ReturnMoments,
    SweepError,
    Trial,
    combinations,
    deflated_sharpe,
    expected_max_sharpe,
    measure,
    overfitting_warnings,
    pick,
    probabilistic_sharpe,
    return_moments,
    session_sharpe,
    trial_key,
)
from tyche.core.domain import BarHistory, Currency

D = Decimal

PAPER_SHARPE = 2.5 / math.sqrt(250)
PAPER_VARIANCE = 0.5 / 250
PAPER_MOMENTS = ReturnMoments(count=1250, sharpe=PAPER_SHARPE, skewness=-3.0, kurtosis=10.0)


class TestTheGrid:
    def test_combinations_change_the_last_parameter_fastest(self) -> None:
        grid = Grid({"a": (1, 2), "b": ("x", "y", "z")})

        found = combinations(grid)

        assert grid.size == 6
        assert [c.number for c in found] == [1, 2, 3, 4, 5, 6]
        assert [dict(c.values) for c in found[:4]] == [
            {"a": 1, "b": "x"},
            {"a": 1, "b": "y"},
            {"a": 1, "b": "z"},
            {"a": 2, "b": "x"},
        ]
        assert found[4].position == (1, 1)

    def test_a_grid_needs_a_parameter_and_values(self) -> None:
        with pytest.raises(SweepError, match="no parameter"):
            Grid({})
        with pytest.raises(SweepError, match="a lists no value"):
            Grid({"a": ()})

    def test_a_value_listed_twice_is_refused(self) -> None:
        with pytest.raises(SweepError, match="more than once"):
            Grid({"a": (1, 2, 1)})


class TestTrialKeys:
    def test_the_same_trial_has_the_same_key_whatever_the_order(self) -> None:
        one = trial_key("p", "1", {"a": 1, "b": [1, 2]})
        two = trial_key("p", "1", {"b": [1, 2], "a": 1})

        assert one == two
        assert one.startswith("sha256:")

    @pytest.mark.parametrize(
        ("plugin", "version", "parameters"),
        [("q", "1", {"a": 1}), ("p", "2", {"a": 1}), ("p", "1", {"a": 2}), ("p", "1", {})],
    )
    def test_any_change_is_another_trial(
        self, plugin: str, version: str, parameters: dict[str, int]
    ) -> None:
        assert trial_key(plugin, version, parameters) != trial_key("p", "1", {"a": 1})


class TestTheExpectedMaximum:
    def test_matches_the_papers_example(self) -> None:
        assert expected_max_sharpe(100, PAPER_VARIANCE) == pytest.approx(0.1132, abs=5e-5)

    def test_one_trial_selects_nothing(self) -> None:
        assert expected_max_sharpe(1, 0.5) == 0.0

    def test_grows_with_the_number_of_trials_and_their_variance(self) -> None:
        assert expected_max_sharpe(10, 0.01) < expected_max_sharpe(100, 0.01)
        assert expected_max_sharpe(10, 0.01) < expected_max_sharpe(10, 0.04)

    def test_refuses_nonsense(self) -> None:
        with pytest.raises(SweepError, match="at least 1"):
            expected_max_sharpe(0, 0.1)
        with pytest.raises(SweepError, match="negative"):
            expected_max_sharpe(2, -0.1)


class TestTheDeflatedSharpeRatio:
    def test_matches_the_papers_example(self) -> None:
        threshold = expected_max_sharpe(100, PAPER_VARIANCE)

        assert probabilistic_sharpe(PAPER_MOMENTS, threshold) == pytest.approx(0.9004, abs=5e-5)

    def test_matches_the_papers_example_with_46_trials(self) -> None:
        threshold = expected_max_sharpe(46, PAPER_VARIANCE)

        assert probabilistic_sharpe(PAPER_MOMENTS, threshold) == pytest.approx(0.9505, abs=5e-5)

    def test_normal_returns_bear_more_trials(self) -> None:
        normal = replace(PAPER_MOMENTS, skewness=0.0, kurtosis=3.0)
        threshold = expected_max_sharpe(88, PAPER_VARIANCE)

        assert probabilistic_sharpe(normal, threshold) == pytest.approx(0.9505, abs=5e-4)

    def test_takes_the_variance_from_the_sharpe_ratios_measured(self) -> None:
        sharpes = [0.01, 0.03, 0.05]

        deflated = deflated_sharpe(PAPER_MOMENTS, sharpes, trials=10)

        assert deflated.variance == pytest.approx(0.0004)
        assert deflated.threshold == pytest.approx(expected_max_sharpe(10, 0.0004))
        assert deflated.trials == 10
        assert deflated.probability == pytest.approx(
            probabilistic_sharpe(PAPER_MOMENTS, deflated.threshold)
        )

    def test_more_trials_lower_it(self) -> None:
        sharpes = [0.01, 0.03, 0.05]

        few = deflated_sharpe(PAPER_MOMENTS, sharpes, trials=3)
        many = deflated_sharpe(PAPER_MOMENTS, sharpes, trials=300)

        assert many.probability < few.probability

    def test_one_trial_is_the_probabilistic_sharpe_ratio_against_zero(self) -> None:
        deflated = deflated_sharpe(PAPER_MOMENTS, [PAPER_SHARPE], trials=1)

        assert deflated.threshold == 0.0
        assert deflated.probability == pytest.approx(probabilistic_sharpe(PAPER_MOMENTS, 0.0))
        assert deflated.significant

    def test_several_trials_need_two_sharpe_ratios_for_a_variance(self) -> None:
        with pytest.raises(SweepError, match="variance is unknown"):
            deflated_sharpe(PAPER_MOMENTS, [0.1], trials=5)

    def test_cannot_count_fewer_trials_than_were_measured(self) -> None:
        with pytest.raises(SweepError, match="2 trials counted, but 3"):
            deflated_sharpe(PAPER_MOMENTS, [0.1, 0.2, 0.3], trials=2)


def curve(*equity: str | int) -> list[EquityPoint]:
    return [
        EquityPoint(close_of(d), D(e), D(0)) for d, e in zip(JANUARY_2024, equity, strict=False)
    ]


class TestReturnMoments:
    def test_summarises_the_daily_returns(self) -> None:
        # Returns: +10%, -10%, +10%, -10%: mean 0, no skew, kurtosis 1.
        moments = return_moments(curve(100, 110, 99, "108.9", "98.01"))

        assert moments is not None
        assert moments.count == 4
        assert moments.sharpe == pytest.approx(0.0, abs=1e-12)
        assert moments.skewness == pytest.approx(0.0, abs=1e-9)
        assert moments.kurtosis == pytest.approx(1.0)

    def test_sharpe_is_the_mean_over_the_sample_deviation(self) -> None:
        points = curve(100, 101, 103, 102, 105)
        returns = [0.01, 2 / 101, -1 / 103, 3 / 102]
        mean = sum(returns) / 4
        sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / 3)

        assert session_sharpe(points) == pytest.approx(mean / sd)

    def test_too_few_returns_or_no_variation_give_none(self) -> None:
        assert return_moments(curve(100, 101, 102)) is None
        assert session_sharpe(curve(100, 100, 100, 100, 100)) is None


BENCHMARK = BarHistory(SPY, tuple(bar(day, 100.0 + i) for i, day in enumerate(JANUARY_2024)))
GRID = Grid({"a": (1, 2, 3), "b": (10, 20)})
COMBINATIONS = combinations(GRID)


def metrics_with(sharpe: str | None) -> BacktestMetrics:
    measured = measure(curve(100, 101, 103, 102, 105), [], BENCHMARK, Currency.USD)
    return replace(
        measured, strategy=replace(measured.strategy, sharpe=None if sharpe is None else D(sharpe))
    )


def trials(*sharpes: str | None) -> list[Trial]:
    return [
        Trial(c, metrics_with(s), None if s is None else float(s) / math.sqrt(252))
        for c, s in zip(COMBINATIONS, sharpes, strict=True)
    ]


class TestThePick:
    def test_is_the_highest_sharpe_ratio(self) -> None:
        best = pick(trials("0.1", "0.9", "0.3", "0.2", "0.4", "0.5"))

        assert best is not None
        assert best.combination.number == 2

    def test_a_tie_goes_to_the_first_in_the_grid(self) -> None:
        best = pick(trials("0.1", "0.9", "0.3", "0.9", "0.4", "0.5"))

        assert best is not None
        assert best.combination.number == 2

    def test_a_trial_without_a_sharpe_ratio_is_never_picked(self) -> None:
        found = trials(None, "-0.5", None, None, None, None)
        failed = Trial(COMBINATIONS[0], None, None, "halted: boom")

        best = pick([failed, *found[1:]])

        assert best is not None
        assert best.combination.number == 2
        assert pick([failed]) is None


def warnings_for(sharpes: list[str | None], probability: float = 0.99) -> tuple[str, ...]:
    found = trials(*sharpes)
    best = pick(found)
    deflated = deflated_sharpe(PAPER_MOMENTS, [0.01, 0.02], trials=2)
    return overfitting_warnings(GRID, found, best, replace(deflated, probability=probability), None)


class TestOverfittingWarnings:
    def test_a_broad_plateau_inside_the_grid_raises_none(self) -> None:
        # a = 2, b = 10 is the pick: a in the middle; b has only two values.
        assert warnings_for(["0.8", "0.7", "0.9", "0.8", "0.8", "0.7"]) == ()

    def test_a_deflated_sharpe_ratio_below_95_percent(self) -> None:
        found = warnings_for(["0.8", "0.7", "0.9", "0.8", "0.8", "0.7"], probability=0.9)

        assert len(found) == 1
        assert "90.0%, below 95%" in found[0]

    def test_a_deflated_sharpe_ratio_that_could_not_be_computed(self) -> None:
        found = trials("0.8", "0.7", "0.9", "0.8", "0.8", "0.7")

        warned = overfitting_warnings(GRID, found, pick(found), None, "no variation")

        assert warned == ("The deflated Sharpe ratio could not be computed: no variation.",)

    def test_a_pick_at_the_edge_of_a_parameter_with_three_values(self) -> None:
        found = warnings_for(["0.8", "0.7", "0.8", "0.7", "0.9", "0.8"])

        assert len(found) == 1
        assert "a is the last value of the grid (3)" in found[0]

    def test_an_isolated_peak(self) -> None:
        # The pick (a = 2, b = 10) has neighbours a = 1, a = 3 and b = 20.
        found = warnings_for(["0.1", "0.1", "0.9", "0.2", "0.4", "0.3"])

        assert len(found) == 1
        assert "isolated peak" in found[0]
        assert "3 neighbours" in found[0]
        assert "median Sharpe ratio of 0.2" in found[0]

    def test_trials_that_failed(self) -> None:
        found = trials("0.8", "0.7", "0.9", "0.8", "0.8", "0.7")
        found[0] = Trial(found[0].combination, None, None, "halted: boom")
        deflated = deflated_sharpe(PAPER_MOMENTS, [0.01, 0.02], trials=6)

        warned = overfitting_warnings(
            GRID, found, pick(found), replace(deflated, probability=1.0), None
        )

        assert warned == (
            "1 of 6 trials halted or could not be measured; they count as trials but add "
            "nothing to the variance.",
        )

    def test_nothing_picked(self) -> None:
        assert overfitting_warnings(GRID, [], None, None, None) == (
            "No trial has a Sharpe ratio, so nothing was picked.",
        )

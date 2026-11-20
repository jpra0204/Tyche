"""Walk-forward: cutting history into folds, and measuring the test windows joined.

Expected values are worked out by hand from the rules in the module docstring.
"""

from datetime import date
from decimal import Decimal

import pytest

from tests.support.market import JANUARY_2024, SPY, bar, close_of
from tyche.core.backtest import (
    BacktestMetrics,
    EquityPoint,
    Fold,
    FoldResult,
    FoldScheme,
    MetricsError,
    WalkForwardError,
    Window,
    chain,
    measure,
    measure_walk_forward,
    plan_folds,
)
from tyche.core.domain import BarHistory, Currency

D = Decimal


def spans(folds: tuple[Fold, ...]) -> list[tuple[str, str]]:
    return [(str(f.train), str(f.test)) for f in folds]


class TestPlanningFolds:
    def test_anchored_training_windows_start_on_the_first_day_and_grow(self) -> None:
        folds = plan_folds(date(2005, 1, 3), date(2008, 12, 31), FoldScheme(2, 1))

        assert spans(folds) == [
            ("2005-01-03 to 2006-12-31", "2007-01-01 to 2007-12-31"),
            ("2005-01-03 to 2007-12-31", "2008-01-01 to 2008-12-31"),
        ]
        assert [f.number for f in folds] == [1, 2]

    def test_rolling_training_windows_keep_their_length(self) -> None:
        folds = plan_folds(date(2005, 1, 3), date(2009, 12, 31), FoldScheme(2, 1, anchored=False))

        assert spans(folds) == [
            ("2005-01-03 to 2006-12-31", "2007-01-01 to 2007-12-31"),
            ("2006-01-01 to 2007-12-31", "2008-01-01 to 2008-12-31"),
            ("2007-01-01 to 2008-12-31", "2009-01-01 to 2009-12-31"),
        ]

    def test_the_default_cuts_2005_to_2023_into_fourteen_one_year_tests(self) -> None:
        folds = plan_folds(date(2005, 1, 3), date(2023, 12, 31), FoldScheme())

        assert len(folds) == 14
        assert str(folds[0].train) == "2005-01-03 to 2009-12-31"
        assert str(folds[-1].test) == "2023-01-01 to 2023-12-31"
        assert str(folds[-1].train) == "2005-01-03 to 2022-12-31"

    def test_test_windows_can_be_several_years_and_the_last_ends_on_the_last_day(self) -> None:
        folds = plan_folds(date(2005, 1, 3), date(2010, 6, 30), FoldScheme(2, 2))

        assert spans(folds) == [
            ("2005-01-03 to 2006-12-31", "2007-01-01 to 2008-12-31"),
            ("2005-01-03 to 2008-12-31", "2009-01-01 to 2010-06-30"),
        ]

    def test_a_start_late_in_the_year_counts_that_year_as_the_first(self) -> None:
        folds = plan_folds(date(2005, 9, 1), date(2007, 12, 31), FoldScheme(2, 1))

        assert spans(folds) == [("2005-09-01 to 2006-12-31", "2007-01-01 to 2007-12-31")]

    def test_a_range_with_no_room_for_a_test_window_is_refused(self) -> None:
        with pytest.raises(WalkForwardError, match="first test window would start on 2010-01-01"):
            plan_folds(date(2005, 1, 3), date(2009, 12, 31), FoldScheme())

    def test_an_empty_range_is_refused(self) -> None:
        with pytest.raises(WalkForwardError, match="empty range"):
            plan_folds(date(2010, 1, 1), date(2009, 1, 1), FoldScheme())

    @pytest.mark.parametrize(("train", "test"), [(0, 1), (1, 0)])
    def test_windows_are_at_least_a_year(self, train: int, test: int) -> None:
        with pytest.raises(WalkForwardError, match="at least 1"):
            FoldScheme(train, test)

    def test_a_window_cannot_end_before_it_starts(self) -> None:
        with pytest.raises(WalkForwardError, match="empty window"):
            Window(date(2010, 1, 2), date(2010, 1, 1))

    def test_a_scheme_says_what_it_is(self) -> None:
        assert str(FoldScheme()) == ("anchored: 5-year first training window, 1-year test windows")
        assert str(FoldScheme(3, 2, anchored=False)) == (
            "rolling: 3-year training window, 2-year test windows"
        )


def curve(days: list[date], *equity: str | int, invested: str | int = 0) -> list[EquityPoint]:
    return [EquityPoint(close_of(d), D(e), D(invested)) for d, e in zip(days, equity, strict=True)]


class TestChaining:
    def test_each_curve_starts_where_the_previous_one_ended(self) -> None:
        first = curve(JANUARY_2024[0:2], 100, 110)
        second = curve(JANUARY_2024[2:4], 200, 180)

        chained = chain([first, second])

        assert [p.equity for p in chained] == [100, 110, 110, 99]
        assert [p.at for p in chained] == [close_of(d) for d in JANUARY_2024[0:4]]

    def test_the_share_invested_is_kept(self) -> None:
        chained = chain([curve(JANUARY_2024[0:1], 100), curve(JANUARY_2024[1:2], 200, invested=50)])

        assert (chained[1].equity, chained[1].invested) == (D(100), D(25))

    def test_curves_that_overlap_in_time_are_refused(self) -> None:
        with pytest.raises(MetricsError, match="overlap"):
            chain([curve(JANUARY_2024[0:2], 100, 110), curve(JANUARY_2024[1:3], 100, 110)])

    def test_nothing_to_chain_is_refused(self) -> None:
        with pytest.raises(MetricsError, match="no equity"):
            chain([])
        with pytest.raises(MetricsError, match="empty"):
            chain([curve(JANUARY_2024[0:1], 100), []])


BENCHMARK = BarHistory(
    SPY,
    tuple(
        bar(day, close)
        for day, close in zip(
            JANUARY_2024, (100.0, 105.0, 110.0, 110.0, 121.0, 121.0), strict=False
        )
    ),
)


def measured(points: list[EquityPoint]) -> BacktestMetrics:
    return measure(points, [], BENCHMARK, Currency.USD)


def two_folds() -> list[FoldResult]:
    """Two test windows of three closes each, in the first six sessions of 2024.

    Fold 1: the strategies make 21%, the benchmark 10%. Fold 2: the strategies lose 1%,
    the benchmark makes 10% (110 to 121).
    """
    days = JANUARY_2024[:6]
    first = curve(days[0:3], 100, 110, 121)
    second = curve(days[3:6], 100, 90, 99)
    window = Window(date(2024, 1, 1), date(2024, 1, 31))
    fold = Fold(1, window, window)
    return [
        FoldResult(fold, measured(first), measured(first), tuple(first)),
        FoldResult(Fold(2, window, window), measured(second), measured(second), tuple(second)),
    ]


class TestMeasuringTheTestWindows:
    def test_the_test_windows_are_joined_and_measured(self) -> None:
        metrics = measure_walk_forward(two_folds())

        assert [p.equity for p in metrics.equity] == [
            D(100),
            D(110),
            D(121),
            D(121),
            D("108.9"),
            D("119.79"),
        ]
        assert metrics.out_of_sample.total_return == D("0.1979")
        assert metrics.out_of_sample.sessions == 6

    def test_the_benchmark_is_joined_the_same_way(self) -> None:
        metrics = measure_walk_forward(two_folds())

        assert [p.equity for p in metrics.benchmark_equity] == [
            D(100),
            D(105),
            D(110),
            D(110),
            D(121),
            D(121),
        ]
        assert metrics.benchmark.total_return == D("0.21")
        assert metrics.versus_benchmark.total_return == D("-0.0121")

    def test_counts_the_test_windows_that_beat_the_benchmark(self) -> None:
        assert measure_walk_forward(two_folds()).tests_ahead == 1

    def test_keeps_every_fold(self) -> None:
        folds = two_folds()

        assert measure_walk_forward(folds).folds == tuple(folds)

    def test_no_fold_is_refused(self) -> None:
        with pytest.raises(MetricsError, match="no fold"):
            measure_walk_forward([])

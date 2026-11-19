"""Metrics: one equity series, the benchmark's total return, trades, and a whole run.

Expected values are worked out by hand from the definitions in the module docstring,
on numbers small enough to check on paper.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tests.support.ledger import fill
from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of, dividend
from tyche.core.backtest import (
    EquityPoint,
    MetricsError,
    benchmark_points,
    closed_trades,
    measure,
    series_metrics,
)
from tyche.core.backtest.metrics import max_drawdown
from tyche.core.domain import BarHistory, Currency, Money, Side

D = Decimal
ANNUAL = D(252).sqrt()
START = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)


def points(*equity: str | int | Decimal, invested: str | int = 0) -> list[EquityPoint]:
    """One point per session close of January 2024."""
    return [
        EquityPoint(close_of(day), D(value), D(invested))
        for day, value in zip(JANUARY_2024, equity, strict=False)
    ]


def close(actual: Decimal | None, expected: Decimal) -> bool:
    assert actual is not None
    return abs(actual - expected) < D("1e-20")


class TestOneSeries:
    def test_total_return_and_cagr_use_calendar_years(self) -> None:
        two_years = START + timedelta(days=730, hours=12)  # 2 x 365.25 days
        series = series_metrics(
            [EquityPoint(START, D(100), D(0)), EquityPoint(two_years, D(200), D(0))]
        )

        assert series.years == 2
        assert series.total_return == 1
        assert close(series.cagr, D(2).sqrt() - 1)
        assert (series.start_equity, series.end_equity, series.sessions) == (D(100), D(200), 2)

    def test_volatility_is_the_annualised_sample_deviation(self) -> None:
        # Returns +10% and -10%: mean 0, sample variance (0.01 + 0.01) / 1.
        series = series_metrics(points(100, 110, 99))

        assert close(series.volatility, D("0.02").sqrt() * ANNUAL)
        assert series.sharpe == 0

    def test_sharpe_is_the_annualised_mean_over_the_deviation(self) -> None:
        # Returns +10%, -10%, +20%: mean 0.2/3, deviations 0.1/3, -0.5/3, 0.4/3.
        series = series_metrics(points(100, 110, 99, D("118.8")))

        mean = D("0.2") / 3
        deviation = ((D("0.01") + D("0.25") + D("0.16")) / 9 / 2).sqrt()
        assert close(series.sharpe, mean / deviation * ANNUAL)

    def test_sortino_divides_by_the_downside_over_every_day(self) -> None:
        # One down day of -10% among three: downside deviation sqrt(0.01 / 3).
        series = series_metrics(points(100, 110, 99, D("118.8")))

        assert close(series.sortino, D("0.2") / 3 / (D("0.01") / 3).sqrt() * ANNUAL)

    def test_ratios_that_cannot_be_computed_are_none(self) -> None:
        steady = series_metrics(points(100, 110, 121))
        single = series_metrics(points(100))

        assert steady.sharpe is None  # no variation
        assert steady.sortino is None  # no down day
        assert single.cagr is None
        assert single.volatility is None
        assert single.sharpe is None
        assert single.total_return == 0

    def test_exposure_is_the_average_fraction_invested(self) -> None:
        series = series_metrics(
            [
                EquityPoint(close_of(JANUARY_2024[0]), D(100), D(0)),
                EquityPoint(close_of(JANUARY_2024[1]), D(100), D(50)),
                EquityPoint(close_of(JANUARY_2024[2]), D(100), D(100)),
            ]
        )

        assert series.exposure == D("0.5")

    def test_points_must_be_in_time_order(self) -> None:
        with pytest.raises(MetricsError, match="strictly increasing"):
            series_metrics(list(reversed(points(100, 110))))

    def test_nothing_to_measure(self) -> None:
        with pytest.raises(MetricsError, match="no equity"):
            series_metrics([])

    def test_equity_must_be_positive(self) -> None:
        with pytest.raises(MetricsError, match="must be positive"):
            EquityPoint(START, D(0), D(0))

    def test_invested_cannot_be_negative(self) -> None:
        with pytest.raises(MetricsError, match="cannot be negative"):
            EquityPoint(START, D(100), D(-1))


class TestMaxDrawdown:
    def test_finds_the_deepest_fall_and_when_it_recovered(self) -> None:
        series = points(100, 120, 90, 110, 130)

        drawdown = max_drawdown(series)

        assert drawdown is not None
        assert drawdown.depth == D("0.25")
        assert (drawdown.peak, drawdown.trough, drawdown.recovered) == (
            series[1].at,
            series[2].at,
            series[4].at,
        )

    def test_a_deeper_later_fall_from_a_lower_peak_wins(self) -> None:
        series = points(100, 90, 95, 60)

        drawdown = max_drawdown(series)

        assert drawdown is not None
        assert drawdown.depth == D("0.4")
        assert drawdown.peak == series[0].at

    def test_not_recovered_by_the_end(self) -> None:
        drawdown = max_drawdown(points(100, 80, 99))

        assert drawdown is not None
        assert drawdown.recovered is None

    def test_none_when_it_never_fell(self) -> None:
        assert max_drawdown(points(100, 100, 101)) is None


def history(*closes: float, distributions: tuple[str, ...] = ()) -> BarHistory:
    """SPY bars on the first sessions of January 2024, with dividends by session index."""
    bars = tuple(bar(day, c) for day, c in zip(JANUARY_2024, closes, strict=False))
    paid = tuple(
        dividend(JANUARY_2024[int(index)], amount)
        for index, amount in (entry.split(":") for entry in distributions)
    )
    return BarHistory(SPY, bars, distributions=paid)


def closes(count: int) -> list[datetime]:
    return [close_of(day) for day in JANUARY_2024[:count]]


class TestTheBenchmark:
    def test_buys_at_the_first_close_and_follows_the_price(self) -> None:
        curve = benchmark_points(history(100.0, 110.0, 99.0), closes(3), D(1000))

        assert [p.equity for p in curve] == [1000, 1100, 990]
        assert all(p.invested == p.equity for p in curve)

    def test_reinvests_each_distribution_at_the_ex_date_close(self) -> None:
        # 10 units; 2.00 a unit on the second session buys 0.2 more at 100.
        curve = benchmark_points(
            history(100.0, 100.0, 102.0, distributions=("1:2.00",)), closes(3), D(1000)
        )

        assert [p.equity for p in curve] == [D(1000), D(1020), D("1040.4")]

    def test_a_distribution_before_the_start_is_not_paid(self) -> None:
        curve = benchmark_points(
            history(100.0, 100.0, distributions=("0:2.00",)), closes(2), D(1000)
        )

        assert [p.equity for p in curve] == [1000, 1000]

    def test_a_missing_session_repeats_the_last_value(self) -> None:
        bars = history(100.0, 110.0, 120.0)
        gap = BarHistory(SPY, (bars.bars[0], bars.bars[2]))

        curve = benchmark_points(gap, closes(3), D(1000))

        assert [p.equity for p in curve] == [1000, 1000, 1200]

    def test_a_distribution_on_a_missing_session_is_reinvested_at_the_next_bar(self) -> None:
        bars = history(100.0, 100.0, 100.0)
        gap = BarHistory(
            SPY, (bars.bars[0], bars.bars[2]), distributions=(dividend(JANUARY_2024[1], "1.00"),)
        )

        curve = benchmark_points(gap, closes(3), D(1000))

        assert [p.equity for p in curve] == [1000, 1000, 1010]

    def test_starts_from_the_latest_bar_before_the_first_close(self) -> None:
        curve = benchmark_points(
            history(100.0, 110.0), [close_of(JANUARY_2024[1]) + timedelta(hours=1)], D(1000)
        )

        assert [p.equity for p in curve] == [1000]

    def test_no_closes_give_no_points(self) -> None:
        assert benchmark_points(history(100.0), [], D(1000)) == ()

    def test_needs_a_bar_to_start_from(self) -> None:
        with pytest.raises(MetricsError, match="no bar of the benchmark SPY@ARCX"):
            benchmark_points(history(100.0), [close_of(date(2023, 12, 29))], D(1000))


class TestTrades:
    def test_a_trade_runs_from_flat_to_flat(self) -> None:
        stats = closed_trades(
            [
                fill(Side.BUY, "10", "100", trade_date=JANUARY_2024[0]),
                fill(Side.BUY, "10", "110", trade_date=JANUARY_2024[1]),
                fill(Side.SELL, "5", "120", trade_date=JANUARY_2024[2]),
                fill(Side.SELL, "15", "105", trade_date=JANUARY_2024[3]),
            ]
        )

        [trade] = stats.closed
        assert (trade.instrument, trade.opened, trade.closed) == (
            SPY,
            JANUARY_2024[0],
            JANUARY_2024[3],
        )
        # Paid 1000 + 1100 + 2 commissions; received 600 + 1575 - 2 commissions.
        assert trade.profit == Money.of("71", Currency.USD)
        assert (stats.wins, stats.win_rate, stats.still_open) == (1, D(1), 0)

    def test_the_win_rate_counts_trades_with_a_profit(self) -> None:
        stats = closed_trades(
            [
                fill(Side.BUY, "10", "100"),
                fill(Side.SELL, "10", "110"),  # +98
                fill(Side.BUY, "10", "100", instrument=QQQ),
                fill(Side.SELL, "10", "100", instrument=QQQ),  # -2: costs make it a loss
                fill(Side.BUY, "10", "100"),
            ]
        )

        assert len(stats.closed) == 2
        assert stats.win_rate == D("0.5")
        assert stats.still_open == 1

    def test_no_closed_trade_has_no_win_rate(self) -> None:
        stats = closed_trades([fill(Side.BUY, "10", "100")])

        assert stats.win_rate is None
        assert stats.still_open == 1

    def test_selling_more_than_is_held_is_refused(self) -> None:
        with pytest.raises(MetricsError, match="only 0 is held"):
            closed_trades([fill(Side.SELL, "1", "100")])


class TestAWholeRun:
    def test_compares_the_run_with_the_benchmark_from_the_same_equity(self) -> None:
        run = points(1000, 1050, 1000, invested=500)
        fills = [fill(Side.BUY, "5", "100", commission="1", trade_date=JANUARY_2024[1])]

        metrics = measure(run, fills, history(100.0, 110.0, 120.0), Currency.USD)

        assert metrics.benchmark_instrument == SPY
        assert [p.equity for p in metrics.benchmark_equity] == [1000, 1100, 1200]
        assert metrics.benchmark.total_return == D("0.2")
        assert metrics.strategy.total_return == 0
        assert metrics.versus_benchmark.total_return == D("-0.2")
        assert metrics.benchmark.max_drawdown is None
        assert metrics.versus_benchmark.max_drawdown == 1 - D(1000) / D(1050)
        assert metrics.traded == Money.of("500", Currency.USD)
        assert metrics.costs == Money.of("1", Currency.USD)
        years = metrics.strategy.years
        assert close(metrics.turnover, D(500) / (D(3050) / 3) / years)

    def test_fills_in_another_currency_are_refused(self) -> None:
        with pytest.raises(MetricsError, match="is in USD, not CAD"):
            measure(
                points(1000, 1000),
                [fill(Side.BUY, "1", "100")],
                history(100.0, 100.0),
                Currency.CAD,
            )

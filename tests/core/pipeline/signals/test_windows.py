"""Bar windows: bounded, ordered, one price basis, filled only by events or the warm-up."""

from datetime import date

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tyche.core.domain import Bar, BarHistory, Instrument, PriceAdjustment, Timeframe
from tyche.core.pipeline.signals import BarWindows, HistoryError, HistoryView, WindowError

D1 = Timeframe.D1


def history(days: list[date], start: float = 100.0) -> BarHistory:
    return BarHistory(SPY, tuple(bar(day, start + i) for i, day in enumerate(days)))


class TestBarWindows:
    def test_keeps_only_the_newest_bars_up_to_capacity(self) -> None:
        windows = BarWindows({D1: 3})
        for i, day in enumerate(JANUARY_2024[:5]):
            windows.add(bar(day, 100.0 + i))

        assert windows.held(SPY, D1) == 3
        assert [b.close for b in windows.last(SPY, D1, 3)] == [102.0, 103.0, 104.0]
        assert [b.close for b in windows.last(SPY, D1, 2)] == [103.0, 104.0]

    def test_windows_are_kept_per_instrument_and_timeframe(self) -> None:
        windows = BarWindows({D1: 5})
        windows.add(bar(JANUARY_2024[0]))
        windows.add(bar(JANUARY_2024[0], instrument=QQQ))
        windows.add(bar(JANUARY_2024[1], instrument=QQQ))

        assert windows.held(SPY, D1) == 1
        assert windows.held(QQQ, D1) == 2
        assert windows.held(SPY, Timeframe.H1) == 0

    def test_bars_of_a_timeframe_nobody_needs_are_ignored(self) -> None:
        windows = BarWindows({D1: 5})
        windows.add(bar(JANUARY_2024[0], timeframe=Timeframe.H1))

        assert windows.held(SPY, Timeframe.H1) == 0

    def test_bars_out_of_order_are_refused(self) -> None:
        windows = BarWindows({D1: 5})
        windows.add(bar(JANUARY_2024[1]))

        with pytest.raises(WindowError, match="out of order"):
            windows.add(bar(JANUARY_2024[0]))
        with pytest.raises(WindowError, match="out of order"):
            windows.add(bar(JANUARY_2024[1]))

    def test_a_bar_on_another_price_basis_is_refused_not_mixed_in(self) -> None:
        windows = BarWindows({D1: 5})
        windows.add(bar(JANUARY_2024[0]))

        with pytest.raises(WindowError, match="rebuilt from the cache"):
            windows.add(bar(JANUARY_2024[1], adjustment=PriceAdjustment.SPLITS_AND_DIVIDENDS))

    def test_asking_for_more_bars_than_held_is_an_error(self) -> None:
        windows = BarWindows({D1: 5})
        windows.add(bar(JANUARY_2024[0]))

        with pytest.raises(WindowError, match="2 bars of SPY@ARCX 1d were asked for, 1 are held"):
            windows.last(SPY, D1, 2)

    def test_capacity_must_be_at_least_one(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            BarWindows({D1: 0})


class TestSeed:
    def test_fills_windows_from_history_up_to_the_given_moment(self) -> None:
        windows = BarWindows({D1: 3})

        windows.seed([history(JANUARY_2024)], through=close_of(JANUARY_2024[4]))

        assert [b.timestamp for b in windows.last(SPY, D1, 3)] == [
            close_of(d) for d in JANUARY_2024[2:5]
        ]

    def test_never_keeps_a_bar_after_the_given_moment(self) -> None:
        windows = BarWindows({D1: 50})

        windows.seed([history(JANUARY_2024)], through=close_of(JANUARY_2024[4]))

        latest = windows.latest(SPY, D1)
        assert latest is not None
        assert latest.timestamp == close_of(JANUARY_2024[4])
        assert windows.held(SPY, D1) == 5

    def test_rebuilds_a_window_rather_than_extending_it(self) -> None:
        # As after a split refetch: the cache's new bars replace the old basis entirely.
        windows = BarWindows({D1: 10})
        windows.seed([history(JANUARY_2024, start=1000.0)], through=close_of(JANUARY_2024[-1]))

        windows.seed([history(JANUARY_2024, start=100.0)], through=close_of(JANUARY_2024[-1]))

        assert [b.close for b in windows.last(SPY, D1, 2)] == [108.0, 109.0]
        assert windows.held(SPY, D1) == 10

    def test_events_continue_where_the_warm_up_stopped(self) -> None:
        windows = BarWindows({D1: 10})
        windows.seed([history(JANUARY_2024[:4])], through=close_of(JANUARY_2024[3]))

        windows.add(bar(JANUARY_2024[4], 200.0))

        assert windows.held(SPY, D1) == 5
        latest = windows.latest(SPY, D1)
        assert latest is not None
        assert latest.close == 200.0

    def test_a_seeded_window_equals_one_built_from_events(self) -> None:
        # The same warm-up path for every mode: a restart sees what a backtest saw.
        seeded = BarWindows({D1: 4})
        seeded.seed([history(JANUARY_2024)], through=close_of(JANUARY_2024[6]))
        replayed = BarWindows({D1: 4})
        for b in history(JANUARY_2024).bars[:7]:
            replayed.add(b)

        assert seeded.last(SPY, D1, 4) == replayed.last(SPY, D1, 4)


class TestHistoryView:
    AS_OF = close_of(JANUARY_2024[2])

    def window(self, days: list[date]) -> dict[tuple[Instrument, Timeframe], tuple[Bar, ...]]:
        return {(SPY, D1): tuple(bar(d, 100.0 + i) for i, d in enumerate(days))}

    def test_returns_the_window_and_its_closes(self) -> None:
        view = HistoryView(self.AS_OF, self.window(JANUARY_2024[:3]), 3)

        assert len(view.bars(SPY, D1)) == 3
        assert view.closes(SPY, D1) == (100.0, 101.0, 102.0)

    def test_an_instrument_outside_the_view_raises_instead_of_returning_nothing(self) -> None:
        view = HistoryView(self.AS_OF, self.window(JANUARY_2024[:3]), 3)

        with pytest.raises(HistoryError, match="QQQ@XNAS"):
            view.bars(QQQ, D1)
        with pytest.raises(HistoryError, match="1h"):
            view.bars(SPY, Timeframe.H1)

    def test_refuses_a_partial_window(self) -> None:
        with pytest.raises(WindowError, match="2 bars, not 3"):
            HistoryView(self.AS_OF, self.window(JANUARY_2024[1:3]), 3)

    def test_refuses_a_window_that_does_not_end_at_the_decision_time(self) -> None:
        with pytest.raises(WindowError, match="does not end"):
            HistoryView(self.AS_OF, self.window(JANUARY_2024[1:4]), 3)

    def test_says_its_decision_time_and_lookback(self) -> None:
        view = HistoryView(self.AS_OF, self.window(JANUARY_2024[:3]), 3)

        assert (view.as_of, view.lookback) == (self.AS_OF, 3)


def test_asking_for_no_bars_is_a_bug() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        BarWindows({D1: 3}).last(SPY, D1, 0)

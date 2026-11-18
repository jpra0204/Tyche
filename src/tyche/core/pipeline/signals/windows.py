"""Bar windows: the recent history the signals stage keeps, and the view strategies get.

``BarWindows`` holds the last bars of each instrument and timeframe, from two sources
only (ADR-0021):

* ``add``, for each ``BarEvent`` the stage is sent during a run;
* ``seed``, the warm-up path, which fills windows from cached ``BarHistory`` up to a
  given moment before a run starts. A backtest uses it to begin with full windows;
  paper and live use it at every start and after a split refetch. It replaces what a
  window held: a window is rebuilt, never patched.

``HistoryView`` is what a strategy sees: for each instrument it may decide on, exactly
``lookback`` bars ending at the decision time. It holds copies, so a strategy cannot
change the stage's windows, and it holds nothing later than the decision time.
"""

from collections import deque
from collections.abc import Iterable, Mapping
from datetime import datetime

from tyche.core.domain import Bar, BarHistory, Instrument, Timeframe
from tyche.core.domain.validation import require_utc

type WindowKey = tuple[Instrument, Timeframe]


class WindowError(Exception):
    """Bars broke an assumption the windows rely on. A bug upstream; the run halts."""


class HistoryError(LookupError):
    """A strategy asked for history it was not given: an instrument outside its window."""


class BarWindows:
    """The last ``capacity`` bars of every instrument, per timeframe.

    Args:
        capacity: How many bars to keep, per timeframe. Bars of a timeframe not listed
            are ignored: no strategy asked for them.
    """

    def __init__(self, capacity: Mapping[Timeframe, int]) -> None:
        for timeframe, size in capacity.items():
            if size < 1:
                raise ValueError(f"window capacity for {timeframe} must be at least 1, got {size}")
        self._capacity = dict(capacity)
        self._windows: dict[WindowKey, deque[Bar]] = {}

    @property
    def capacity(self) -> Mapping[Timeframe, int]:
        return dict(self._capacity)

    def add(self, bar: Bar) -> None:
        """Append the next bar of its instrument and timeframe."""
        size = self._capacity.get(bar.timeframe)
        if size is None:
            return
        key = (bar.instrument, bar.timeframe)
        window = self._windows.setdefault(key, deque(maxlen=size))
        if window:
            newest = window[-1]
            if bar.timestamp <= newest.timestamp:
                raise WindowError(
                    f"bars of {bar.instrument} {bar.timeframe} arrived out of order: "
                    f"{bar.timestamp.isoformat()} after {newest.timestamp.isoformat()}"
                )
            if bar.adjustment is not newest.adjustment:
                raise WindowError(
                    f"a bar of {bar.instrument} at {bar.timestamp.isoformat()} is adjusted "
                    f"for '{bar.adjustment}', the window for '{newest.adjustment}'; windows "
                    "are rebuilt from the cache when the basis changes, never mixed (ADR-0021)"
                )
        window.append(bar)

    def seed(self, histories: Iterable[BarHistory], *, through: datetime) -> None:
        """Rebuild windows from cached history, keeping only bars at or before ``through``.

        Each history's window is replaced, not extended. Call it before the run's first
        event, with ``through`` no later than that event's moment; a bar the clock has
        not reached would otherwise be in a window (lookahead).
        """
        require_utc(through, "seed through")
        for history in histories:
            for timeframe in self._capacity:
                self._windows.pop((history.instrument, timeframe), None)
            for bar in history.bars:
                if bar.timestamp <= through:
                    self.add(bar)

    def held(self, instrument: Instrument, timeframe: Timeframe) -> int:
        """How many bars are held for ``instrument`` at ``timeframe``."""
        window = self._windows.get((instrument, timeframe))
        return len(window) if window else 0

    def latest(self, instrument: Instrument, timeframe: Timeframe) -> Bar | None:
        """The newest bar held, or ``None``."""
        window = self._windows.get((instrument, timeframe))
        return window[-1] if window else None

    def last(self, instrument: Instrument, timeframe: Timeframe, count: int) -> tuple[Bar, ...]:
        """The newest ``count`` bars, oldest first. Raises if fewer are held."""
        if count < 1:
            raise ValueError(f"count must be at least 1, got {count}")
        window = self._windows.get((instrument, timeframe), deque())
        if len(window) < count:
            raise WindowError(
                f"{count} bars of {instrument} {timeframe} were asked for, {len(window)} are held"
            )
        return tuple(window)[-count:]


class HistoryView:
    """The read-only history one strategy is given at one decision time.

    Every window holds exactly ``lookback`` bars, oldest first, and ends at ``as_of``.
    Asking for an instrument or a timeframe outside the view raises ``HistoryError``,
    so a partial or missing window can never be mistaken for a full one.

    Args:
        as_of: The decision time.
        windows: The bars per instrument and timeframe.
        lookback: The number of bars every window holds.
    """

    def __init__(
        self, as_of: datetime, windows: Mapping[WindowKey, tuple[Bar, ...]], lookback: int
    ) -> None:
        require_utc(as_of, "HistoryView as_of")
        for (instrument, timeframe), bars in windows.items():
            if len(bars) != lookback:
                raise WindowError(
                    f"the view for {instrument} {timeframe} has {len(bars)} bars, not {lookback}"
                )
            if bars[-1].timestamp != as_of or any(b.timestamp > as_of for b in bars):
                raise WindowError(
                    f"the view for {instrument} {timeframe} does not end at {as_of.isoformat()}"
                )
        self._as_of = as_of
        self._windows = dict(windows)
        self._lookback = lookback

    @property
    def as_of(self) -> datetime:
        return self._as_of

    @property
    def lookback(self) -> int:
        return self._lookback

    def bars(self, instrument: Instrument, timeframe: Timeframe) -> tuple[Bar, ...]:
        """Exactly ``lookback`` bars of ``instrument``, oldest first, ending at ``as_of``."""
        bars = self._windows.get((instrument, timeframe))
        if bars is None:
            raise HistoryError(
                f"no {timeframe} history for {instrument} in this view: only the instruments "
                "in the context's ranking, at the strategy's own timeframe, have a window"
            )
        return bars

    def closes(self, instrument: Instrument, timeframe: Timeframe) -> tuple[float, ...]:
        """The closes of ``bars(instrument, timeframe)``, oldest first."""
        return tuple(bar.close for bar in self.bars(instrument, timeframe))

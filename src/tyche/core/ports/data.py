"""The DataProvider port: how the core asks for market data."""

from datetime import date
from typing import Protocol

from tyche.core.domain.bar_history import BarHistory
from tyche.core.domain.instrument import Instrument


class DataError(Exception):
    """Market data could not be obtained or stored."""


class DataProvider(Protocol):
    """Supplies audited daily bars.

    The core never talks to a data vendor. It asks this port, and gets back bars that
    have been checked against the trading calendar, together with every problem found
    (see ``BarHistory``). Where the bars come from, and whether they were cached, is the
    adapter's business.
    """

    def daily_bars(self, instrument: Instrument, first: date, last: date) -> BarHistory:
        """Return bars for every session of ``instrument`` from ``first`` to ``last``.

        Dates are session days on the instrument's own calendar, inclusive. Sessions
        that have not closed yet are not expected to have a bar. A session the source
        has no bar for appears as a ``MISSING_SESSION`` issue, not as an error.

        Raises:
            DataError: The data could not be obtained at all.
        """
        ...

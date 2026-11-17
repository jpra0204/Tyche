"""``Calendar`` adapters.

Available now: ``ExchangeCalendarsCalendar``, which serves any market the
``exchange_calendars`` library knows. ``XNYS`` covers every US exchange.

Planned (Phase 4): TSX (``XTSE``) is already served by the same adapter and gets its
tests with the ``CA`` market profile.
"""

from tyche.adapters.calendars.exchange_calendars_adapter import ExchangeCalendarsCalendar

__all__ = ["ExchangeCalendarsCalendar"]

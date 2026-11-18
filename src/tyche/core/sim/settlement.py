"""When a trade settles: T+n sessions on the instrument's trading calendar (ADR-0020).

Known limit: real settlement follows the settlement system's business days, which may
not match the exchange's sessions on every date (a day when the exchange is open but
the settlement system is not, or the reverse). That difference is not verified and not
modelled; it could put a few settlement dates a year one day off.
"""

from datetime import date

from tyche.core.ports.calendar import Calendar


def settlement_date(trade_date: date, settlement_days: int, calendar: Calendar) -> date:
    """The date a trade on ``trade_date`` settles, ``settlement_days`` sessions later.

    Raises ``ValueError`` if ``trade_date`` is not a session on ``calendar``: a trade
    on a closed day is a bug upstream, not something to round to the next session.
    """
    if settlement_days < 0:
        raise ValueError(f"settlement_days must be zero or more, got {settlement_days}")
    if calendar.session_on(trade_date) is None:
        raise ValueError(f"{trade_date.isoformat()} is not a {calendar.mic} session")
    settles = trade_date
    for _ in range(settlement_days):
        settles = calendar.next_session(settles).day
    return settles

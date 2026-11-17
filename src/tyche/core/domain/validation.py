"""Small checks shared by the value objects."""

import re
from datetime import datetime, timedelta

_ZERO_OFFSET = timedelta(0)
# ISO 10383 market identifier code: four upper-case letters or digits, e.g. XNYS.
_MIC = re.compile(r"[A-Z0-9]{4}")


def require_utc(moment: datetime, what: str) -> None:
    """Raise ``ValueError`` unless ``moment`` is timezone-aware with a zero UTC offset.

    Every timestamp in the core is UTC (ADR-0012). A naive datetime, or one in a local
    timezone, is a bug waiting for a daylight-saving change.
    """
    if moment.utcoffset() != _ZERO_OFFSET:
        raise ValueError(f"{what} must be timezone-aware UTC, got {moment!r}")


def require_mic(code: str, what: str) -> None:
    """Raise ``ValueError`` unless ``code`` has the shape of a market identifier code."""
    if not _MIC.fullmatch(code):
        raise ValueError(f"invalid {what} {code!r}: expected a 4-character MIC")

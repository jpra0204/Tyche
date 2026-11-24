"""Structured logs in daily files, with secrets redacted (ADR-0040).

Available now: ``configure_logging``, which sends the ``tyche`` logger's records to
``logs/<UTC date>.jsonl`` in the workspace, one JSON object per line, and
``close_logging``. ``JsonLinesFormatter`` hides the ``.env`` secrets and any Discord
webhook URL in every line it writes.
"""

from tyche.adapters.logs.json_lines import (
    LOGGER,
    REDACTED,
    DailyFileHandler,
    JsonLinesFormatter,
    close_logging,
    configure_logging,
)

__all__ = [
    "LOGGER",
    "REDACTED",
    "DailyFileHandler",
    "JsonLinesFormatter",
    "close_logging",
    "configure_logging",
]

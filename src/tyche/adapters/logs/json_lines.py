"""Structured logs: one JSON object per line, one file per UTC day (ADR-0040).

Each line looks like::

    {"at": "2026-11-23T21:04:05.120Z", "level": "INFO", "logger": "tyche.cli",
     "message": "kill switch engaged", "command": "kill", "flatten": false}

Extra fields come from ``logger.info("...", extra={"fields": {...}})``. Files are
``logs/<YYYY-MM-DD>.jsonl``, named by the UTC date of each record, so a process that
runs past midnight UTC moves on to the next file by itself. A log line's time is the
wall clock when it was written; trading time always comes from the ``Clock`` port.

**Secrets are redacted in the formatter**, from the finished line, so nothing reaches
the file unredacted: not the message, not an extra field, not a traceback. It hides
every value it is given (the ``.env`` secrets) and anything shaped like a Discord
webhook URL, given or not. The folder is created readable by its owner only, and so is
each file: logs say what Tyche did with the account.
"""

import json
import logging
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, override

LOGGER = "tyche"
"""Tyche's own logger; every module logs under it (``tyche.cli``, ``tyche.runtime``)."""

REDACTED = "[redacted]"

_WEBHOOK = re.compile(
    r"https?://(?:[\w-]+\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/[^\s\"']+"
)


class JsonLinesFormatter(logging.Formatter):
    """Formats a record as one JSON line, with every secret replaced by ``[redacted]``.

    Args:
        secrets: Values to hide wherever they appear, such as ``Secrets.values()``.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(sorted({s for s in secrets if s}, key=len, reverse=True))

    @override
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "at": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                entry.setdefault(str(key), value)
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        return self.redact(line)

    def redact(self, text: str) -> str:
        """``text`` with every secret and every webhook URL replaced."""
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
            escaped = json.dumps(secret, ensure_ascii=False)[1:-1]
            if escaped != secret:
                text = text.replace(escaped, REDACTED)
        return _WEBHOOK.sub(REDACTED, text)


class DailyFileHandler(logging.Handler):
    """Appends each record to ``<directory>/<UTC date>.jsonl``.

    Args:
        directory: The workspace's ``logs/`` folder; created if missing.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._directory = directory
        self._day: str | None = None
        self._stream: IO[str] | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    def path_for(self, day: str) -> Path:
        return self._directory / f"{day}.jsonl"

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            day = datetime.fromtimestamp(record.created, UTC).date().isoformat()
            stream = self._open(day)
            stream.write(line + "\n")
            stream.flush()
        except Exception:  # logging must never stop Tyche; report it the standard way
            self.handleError(record)

    @override
    def close(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
                self._day = None
        finally:
            self.release()
        super().close()

    def _open(self, day: str) -> IO[str]:
        if self._stream is not None and self._day == day:
            return self._stream
        if self._stream is not None:
            self._stream.close()
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path_for(day), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._stream = os.fdopen(descriptor, "a", encoding="utf-8")
        self._day = day
        return self._stream


def configure_logging(
    directory: Path, *, secrets: Iterable[str] = (), level: int = logging.INFO
) -> DailyFileHandler:
    """Send Tyche's logs to daily files in ``directory``, redacted. Replaces any earlier setup.

    Only the ``tyche`` logger is configured; it does not pass records on to the root
    logger, so nothing is printed twice and a library's own logging is left alone.
    """
    logger = logging.getLogger(LOGGER)
    close_logging()
    handler = DailyFileHandler(directory)
    handler.setFormatter(JsonLinesFormatter(secrets))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return handler


def close_logging() -> None:
    """Close and remove every daily-file handler on Tyche's logger, and undo the setup."""
    logger = logging.getLogger(LOGGER)
    for handler in list(logger.handlers):
        if isinstance(handler, DailyFileHandler):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True

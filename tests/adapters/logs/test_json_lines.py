"""Structured daily logs with secrets redacted (ADR-0040)."""

import json
import logging
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from tyche.adapters.logs import REDACTED, DailyFileHandler, JsonLinesFormatter, configure_logging

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/secret-token"
NOON = datetime(2026, 11, 23, 12, 0, tzinfo=UTC).timestamp()


def record(
    message: str, *args: object, created: float = NOON, **extra: object
) -> logging.LogRecord:
    entry = logging.LogRecord("tyche.test", logging.INFO, __file__, 1, message, args, None)
    entry.created = created
    for key, value in extra.items():
        setattr(entry, key, value)
    return entry


class TestFormatter:
    def test_one_json_object_with_the_time_in_utc(self) -> None:
        line = JsonLinesFormatter().format(record("ran %s", "backtest", fields={"run": "r1"}))
        assert json.loads(line) == {
            "at": "2026-11-23T12:00:00.000Z",
            "level": "INFO",
            "logger": "tyche.test",
            "message": "ran backtest",
            "run": "r1",
        }

    def test_a_field_never_replaces_the_standard_keys(self) -> None:
        line = JsonLinesFormatter().format(record("x", fields={"message": "forged"}))
        assert json.loads(line)["message"] == "x"

    def test_values_that_are_not_json_are_written_as_text(self) -> None:
        line = JsonLinesFormatter().format(record("x", fields={"path": Path("/a")}))
        assert json.loads(line)["path"] == "/a"

    def test_hides_every_secret_it_is_given_wherever_it_is(self) -> None:
        formatter = JsonLinesFormatter(["DU111"])
        line = formatter.format(record("account %s", "DU111", fields={"id": "DU111"}))
        assert "DU111" not in line
        assert json.loads(line)["id"] == REDACTED

    def test_hides_any_webhook_url_even_one_it_was_not_given(self) -> None:
        line = JsonLinesFormatter().format(record(f"posting to {WEBHOOK}?wait=true"))
        assert "secret-token" not in line
        assert json.loads(line)["message"] == f"posting to {REDACTED}"

    def test_hides_secrets_in_a_traceback(self) -> None:
        try:
            raise RuntimeError(f"failed {WEBHOOK}")
        except RuntimeError:
            entry = logging.LogRecord(
                "tyche.test", logging.ERROR, __file__, 1, "crashed", (), sys.exc_info()
            )
        line = JsonLinesFormatter([WEBHOOK]).format(entry)
        assert "secret-token" not in line
        assert "RuntimeError" in json.loads(line)["error"]


class TestDailyFiles:
    def test_one_file_per_utc_day(self, tmp_path: Path) -> None:
        handler = DailyFileHandler(tmp_path / "logs")
        handler.setFormatter(JsonLinesFormatter())
        late = datetime(2026, 11, 23, 23, 59, 59, tzinfo=UTC).timestamp()
        handler.handle(record("first", created=late))
        handler.handle(record("second", created=late + 2))
        handler.close()
        first = (tmp_path / "logs/2026-11-23.jsonl").read_text().splitlines()
        second = (tmp_path / "logs/2026-11-24.jsonl").read_text().splitlines()
        assert [json.loads(line)["message"] for line in first] == ["first"]
        assert [json.loads(line)["message"] for line in second] == ["second"]

    def test_appends_to_the_days_file(self, tmp_path: Path) -> None:
        for message in ("one", "two"):
            handler = DailyFileHandler(tmp_path)
            handler.setFormatter(JsonLinesFormatter())
            handler.handle(record(message))
            handler.close()
        lines = (tmp_path / "2026-11-23.jsonl").read_text().splitlines()
        assert [json.loads(line)["message"] for line in lines] == ["one", "two"]

    def test_folder_and_files_are_private(self, tmp_path: Path) -> None:
        handler = DailyFileHandler(tmp_path / "logs")
        handler.setFormatter(JsonLinesFormatter())
        handler.handle(record("x"))
        handler.close()
        assert stat.S_IMODE((tmp_path / "logs").stat().st_mode) == 0o700
        assert stat.S_IMODE((tmp_path / "logs/2026-11-23.jsonl").stat().st_mode) == 0o600


class TestConfigure:
    def test_sends_tyches_logs_to_the_folder_redacted(self, tmp_path: Path) -> None:
        handler = configure_logging(tmp_path, secrets=["DU111"])
        logging.getLogger("tyche.cli").info("account DU111")
        day = datetime.now(UTC).date().isoformat()
        line = handler.path_for(day).read_text()
        assert "DU111" not in line
        assert REDACTED in line

    def test_a_second_setup_replaces_the_first(self, tmp_path: Path) -> None:
        configure_logging(tmp_path / "a")
        configure_logging(tmp_path / "b")
        handlers = [
            h for h in logging.getLogger("tyche").handlers if isinstance(h, DailyFileHandler)
        ]
        assert [h.directory for h in handlers] == [tmp_path / "b"]

    def test_does_not_pass_records_to_the_root_logger(self, tmp_path: Path) -> None:
        configure_logging(tmp_path)
        assert logging.getLogger("tyche").propagate is False

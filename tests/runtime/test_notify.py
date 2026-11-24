"""Sending alerts from the runtime: never failing a command (ADR-0040)."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.core.risk.test_gate import drawdown
from tests.support.kill import kill
from tests.support.recording import TickingClock
from tyche.adapters.logs import configure_logging
from tyche.adapters.notifiers import DiscordWebhookNotifier
from tyche.config import Secrets
from tyche.config.workspace import Workspace
from tyche.core.ports import Alert, AlertKind, NotifierError
from tyche.runtime.notify import (
    ChannelCheckError,
    Delivery,
    build_notifier,
    check_channel,
    deliver,
    notify,
    notify_kill,
    notify_resume,
)

AT = datetime(2026, 11, 23, 21, 4, tzinfo=UTC)
WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/secret-token"


def alert(title: str = "something") -> Alert:
    return Alert(AlertKind.KILL_SWITCH, title, AT)


class FakeNotifier:
    def __init__(self, *failing: str) -> None:
        self.sent: list[Alert] = []
        self._failing = set(failing)

    def send(self, alert: Alert) -> None:
        if alert.title in self._failing:
            raise NotifierError(f"could not send {alert.title}")
        self.sent.append(alert)


def workspace(tmp_path: Path, env: str = "") -> Workspace:
    (tmp_path / ".env").write_text(env)
    return Workspace(tmp_path)


class TestDeliver:
    def test_sends_each_alert_in_order(self) -> None:
        notifier = FakeNotifier()
        delivery = deliver(notifier, [alert("a"), alert("b")])
        assert [a.title for a in notifier.sent] == ["a", "b"]
        assert delivery == Delivery(sent=2)
        assert delivery.describe() == "Discord: 2 alerts sent."

    def test_a_failure_does_not_stop_the_others(self) -> None:
        notifier = FakeNotifier("a")
        delivery = deliver(notifier, [alert("a"), alert("b")])
        assert [a.title for a in notifier.sent] == ["b"]
        assert delivery.failures == ("could not send a",)
        assert delivery.describe() == "Discord: 1 sent, 1 not sent: could not send a"

    def test_without_a_notifier_nothing_is_tried(self) -> None:
        delivery = deliver(None, [alert()])
        assert not delivery.configured
        assert "DISCORD_WEBHOOK_URL is empty" in delivery.describe()

    def test_logs_each_outcome(self, tmp_path: Path) -> None:
        handler = configure_logging(tmp_path)
        deliver(FakeNotifier("a"), [alert("a"), alert("b")])
        day = datetime.now(UTC).date().isoformat()
        entries = [json.loads(line) for line in handler.path_for(day).read_text().splitlines()]
        assert [(e["level"], e["message"], e["title"]) for e in entries] == [
            ("WARNING", "alert not sent: could not send a", "a"),
            ("INFO", "alert sent", "b"),
        ]


class TestNotify:
    def test_no_webhook_means_not_configured(self, tmp_path: Path) -> None:
        delivery = notify(workspace(tmp_path), [alert()], environ={}, code_version="0.1.0")
        assert not delivery.configured

    def test_a_broken_env_is_a_failure_not_an_error(self, tmp_path: Path) -> None:
        broken = workspace(tmp_path, "NOT_A_KEY=1\n")
        delivery = notify(broken, [alert(), alert()], environ={}, code_version="0.1.0")
        assert len(delivery.failures) == 2
        assert "unknown key NOT_A_KEY" in delivery.failures[0]

    def test_builds_the_discord_notifier_from_the_webhook(self) -> None:
        secrets = Secrets(discord_webhook_url=SecretStr(WEBHOOK))
        assert isinstance(build_notifier(secrets, code_version="0.1.0"), DiscordWebhookNotifier)
        assert build_notifier(Secrets(), code_version="0.1.0") is None

    def test_kill_and_resume_without_a_webhook_send_nothing(self, tmp_path: Path) -> None:
        place = workspace(tmp_path)
        assert not notify_kill(place, kill(), environ={}, code_version="0.1.0").configured
        resumed = notify_resume(
            place,
            "checked",
            released=kill(),
            lifted=drawdown(),
            environ={},
            code_version="0.1.0",
            clock=TickingClock(AT),
        )
        assert not resumed.configured


class TestCheckChannel:
    def test_needs_a_webhook(self, tmp_path: Path) -> None:
        with pytest.raises(ChannelCheckError, match="DISCORD_WEBHOOK_URL is not set"):
            check_channel(workspace(tmp_path), environ={}, code_version="0.1.0")

    def test_reports_a_broken_env(self, tmp_path: Path) -> None:
        with pytest.raises(ChannelCheckError, match="unknown key"):
            check_channel(workspace(tmp_path, "X_Y=1\n"), environ={}, code_version="0.1.0")

    def test_reports_an_unreachable_discord_without_the_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreachable(*_: object) -> None:
            raise NotifierError("cannot reach Discord: timed out")

        monkeypatch.setattr(
            "tyche.adapters.notifiers.discord.DiscordWebhookNotifier.send", unreachable
        )
        place = workspace(tmp_path, f"DISCORD_WEBHOOK_URL={WEBHOOK}\n")
        with pytest.raises(ChannelCheckError, match="cannot reach Discord") as raised:
            check_channel(place, environ={}, code_version="0.1.0")
        assert "secret-token" not in str(raised.value)


def test_runtime_logs_never_show_the_webhook(tmp_path: Path) -> None:
    handler = configure_logging(tmp_path / "logs", secrets=[WEBHOOK])
    logging.getLogger("tyche.runtime").warning("posting to %s", WEBHOOK)
    day = datetime.now(UTC).date().isoformat()
    assert "secret-token" not in handler.path_for(day).read_text()

"""Sending alerts: from the workspace's secrets to the Discord channel (ADR-0040).

A failure to notify never stops a command or a run. Every outcome is logged, and the
caller gets a ``Delivery`` to print: sent, not configured, or why it failed.

Backtests, walk-forwards, sweeps and the other research commands never notify. The
paper run (Phase 2, PR 14) is the first run to send its ``AlertCollector``'s alerts,
after it ends, and ``run_failed_alert`` when it fails.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from tyche.adapters.clocks import SystemClock
from tyche.adapters.notifiers import DiscordWebhookNotifier
from tyche.config import DISCORD_WEBHOOK_URL, EnvFileError, Secrets, Workspace, load_secrets
from tyche.core.domain import AccountTrigger, Kill, Reconciliation
from tyche.core.pipeline.alerts import channel_check_alert, kill_alert, resumed_alert
from tyche.core.ports import Alert, Clock, Notifier, NotifierError

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Delivery:
    """What became of a batch of alerts.

    Attributes:
        sent: How many were delivered.
        failures: Why each of the others was not, without secrets.
        configured: False when no notifier is set up, so nothing was tried.
    """

    sent: int = 0
    failures: tuple[str, ...] = ()
    configured: bool = True

    def describe(self) -> str:
        """One line for the terminal."""
        if not self.configured:
            return f"Discord: not set up ({DISCORD_WEBHOOK_URL} is empty); nothing sent."
        if not self.failures:
            noun = "alert" if self.sent == 1 else "alerts"
            return f"Discord: {self.sent} {noun} sent."
        return f"Discord: {self.sent} sent, {len(self.failures)} not sent: {self.failures[0]}"


def build_notifier(secrets: Secrets, *, code_version: str) -> Notifier | None:
    """The Discord notifier, or ``None`` when no webhook is given."""
    if secrets.discord_webhook_url is None:
        return None
    return DiscordWebhookNotifier(secrets.discord_webhook_url, code_version=code_version)


def deliver(notifier: Notifier | None, alerts: Iterable[Alert]) -> Delivery:
    """Send each alert in order, logging each outcome. Never raises ``NotifierError``."""
    batch = tuple(alerts)
    if notifier is None:
        for alert in batch:
            _log.info("alert not sent: no notifier", extra={"fields": _fields(alert)})
        return Delivery(configured=False)
    sent = 0
    failures: list[str] = []
    for alert in batch:
        try:
            notifier.send(alert)
        except NotifierError as error:
            failures.append(str(error))
            _log.warning(
                "alert not sent: %s", error, extra={"fields": _fields(alert, error=str(error))}
            )
        else:
            sent += 1
            _log.info("alert sent", extra={"fields": _fields(alert)})
    return Delivery(sent, tuple(failures))


def notify(
    workspace: Workspace,
    alerts: Iterable[Alert],
    *,
    environ: Mapping[str, str],
    code_version: str,
) -> Delivery:
    """Read the workspace's secrets and send ``alerts``.

    A broken ``.env`` is reported as a failure to deliver, not raised.
    """
    batch = tuple(alerts)
    try:
        secrets = load_secrets(workspace.env_file, environ)
    except EnvFileError as error:
        _log.warning("alerts not sent: %s", error, extra={"fields": {"alerts": len(batch)}})
        return Delivery(failures=(str(error),) * max(len(batch), 1))
    return deliver(build_notifier(secrets, code_version=code_version), batch)


def notify_kill(
    workspace: Workspace,
    kill: Kill,
    *,
    environ: Mapping[str, str],
    code_version: str,
    clock: Clock | None = None,
) -> Delivery:
    """``tyche kill`` engaged the switch: say so, at the time it was engaged."""
    at = kill.engaged_at or (clock or SystemClock()).now()
    return notify(workspace, [kill_alert(kill, at)], environ=environ, code_version=code_version)


def notify_resume(
    workspace: Workspace,
    reason: str,
    *,
    released: Kill | None,
    lifted: AccountTrigger | None,
    environ: Mapping[str, str],
    code_version: str,
    unreconciled: Reconciliation | None = None,
    applied: bool = False,
    clock: Clock | None = None,
) -> Delivery:
    """``tyche resume`` lifted the kill switch or a halt."""
    at = (clock or SystemClock()).now()
    alert = resumed_alert(
        reason,
        at,
        released=released,
        lifted=lifted,
        reconciliation=unreconciled,
        applied=applied,
    )
    return notify(workspace, [alert], environ=environ, code_version=code_version)


class ChannelCheckError(Exception):
    """``tyche notify test`` could not reach the channel. Never contains a secret."""


def check_channel(
    workspace: Workspace,
    *,
    environ: Mapping[str, str],
    code_version: str,
    clock: Clock | None = None,
) -> None:
    """Send the test message of ``tyche notify test``.

    Raises:
        ChannelCheckError: ``.env`` is invalid, no webhook is set, or the message was
            not delivered.
    """
    try:
        secrets = load_secrets(workspace.env_file, environ)
    except EnvFileError as error:
        raise ChannelCheckError(str(error)) from None
    notifier = build_notifier(secrets, code_version=code_version)
    if notifier is None:
        raise ChannelCheckError(
            f"{DISCORD_WEBHOOK_URL} is not set in {workspace.env_file} or the environment"
        )
    delivery = deliver(notifier, [channel_check_alert((clock or SystemClock()).now())])
    if delivery.failures:
        raise ChannelCheckError(delivery.failures[0])


def _fields(alert: Alert, **more: str) -> dict[str, object]:
    return {
        "alert": str(alert.kind),
        "title": alert.title,
        "alert_at": alert.at.isoformat(),
        "lines": list(alert.lines),
        **more,
    }

"""The Notifier port: telling Pablo that something needs his attention (ADR-0040).

An ``Alert`` is a short, finished message: what happened, when, and what to look at.
The core builds alerts from events (``tyche.core.pipeline.alerts``) and never sends
them itself; the runtime hands them to a ``Notifier`` after a run, or straight away
for a command such as ``tyche kill``.

There is no ``NotificationEvent``: an alert describes events that happened, so nothing
can ask the notifier to say something that did not (event catalog).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from tyche.core.domain.validation import require_utc


class AlertKind(StrEnum):
    """What an alert is about: the alerts of brief §9 that exist so far."""

    RISK_LIMIT = "risk_limit"
    """An account rule reached its limit: the daily loss limit or the drawdown kill."""

    KILL_SWITCH = "kill_switch"
    """The kill switch was engaged, or a run found it engaged."""

    RESUMED = "resumed"
    """``tyche resume`` lifted the kill switch, the drawdown halt, or both."""

    DATA_FAILURE = "data_failure"
    """Market data had problems the audit found."""

    RUN_FAILED = "run_failed"
    """A run stopped with an error before it finished."""

    TEST = "test"
    """``tyche notify test``: checks that the channel works. Nothing happened."""


@dataclass(frozen=True, slots=True)
class Alert:
    """One message for Pablo.

    Attributes:
        kind: What it is about.
        title: One line, read first: what happened.
        at: When it happened, in UTC.
        lines: Details, one fact per line, in the order to read them.
    """

    kind: AlertKind
    title: str
    at: datetime
    lines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.at, "Alert at")
        if not self.title.strip():
            raise ValueError("Alert: needs a title")
        if "\n" in self.title:
            raise ValueError("Alert: the title is one line")


class NotifierError(Exception):
    """An alert could not be delivered.

    The message never contains a secret, such as the webhook URL, so it can be printed
    and logged as it is.
    """


class Notifier(Protocol):
    """Delivers alerts to Pablo: today a Discord channel, later others (brief §9)."""

    def send(self, alert: Alert) -> None:
        """Deliver ``alert``, or raise ``NotifierError``.

        A failure to notify must never stop trading or a command: callers catch the
        error, log it, and carry on.
        """
        ...

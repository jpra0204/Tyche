"""Turning events into alerts, and collecting a run's alerts until it ends (ADR-0040).

What is an alert, and what is not:

* **The daily loss limit and the drawdown kill** (an ``AccountTrigger`` on a
  ``RiskEvent``): each is one alert, when it triggers. The approvals that carry the
  drawdown halt afterwards add nothing new.
* **Routine risk cuts are not alerts**: a position shrunk to the profile's size, an
  entry blocked by the position count, a purchase cut to the money caps. A capped
  position is cut at every close, so they belong in the daily summary (PR 16).
* **The kill switch**, once per run, at the first approval that carries it.
* **Data problems**: every ``DataQualityEvent`` of the run, in one alert, so a bad
  download cannot flood the channel.
* **A failed run**, built by the runtime with ``run_failed_alert``, because a run that
  fails cannot publish anything more.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from tyche.core.domain import AccountTrigger, DataIssue, Kill, RiskRule
from tyche.core.events import (
    ApprovedPortfolioEvent,
    DataQualityEvent,
    Envelope,
    EventBus,
    RiskEvent,
    RunMode,
)
from tyche.core.ports import Alert, AlertKind

SUBSCRIBER = "alerts"

MAX_ISSUES_LISTED = 10
"""Data issues listed one by one in an alert; the rest are counted."""

KILL_SWITCH_RUNBOOK = "docs/runbooks/kill-switch.md"


class AlertCollector:
    """Keeps the alerts of one run, in the order they happened.

    Subscribe it before anything is published (the bus refuses late subscribers). It
    only reads events: it publishes nothing and never fails a run over an event it
    does not alert on.
    """

    def __init__(self, bus: EventBus) -> None:
        self._alerts: list[Alert] = []
        self._issues: list[DataIssue] = []
        self._issues_at: datetime | None = None
        self._kill_seen = False
        bus.subscribe(RiskEvent, self._on_risk, name=SUBSCRIBER)
        bus.subscribe(ApprovedPortfolioEvent, self._on_approval, name=SUBSCRIBER)
        bus.subscribe(DataQualityEvent, self._on_data_quality, name=SUBSCRIBER)

    def alerts(self) -> tuple[Alert, ...]:
        """Every alert so far, the run's data problems last, as one alert."""
        collected = list(self._alerts)
        if self._issues and self._issues_at is not None:
            collected.append(data_failure_alert(self._issues, self._issues_at))
        return tuple(collected)

    def _on_risk(self, envelope: Envelope[RiskEvent]) -> None:
        alert = risk_limit_alert(envelope.event, envelope.occurred_at)
        if alert is not None:
            self._alerts.append(alert)

    def _on_approval(self, envelope: Envelope[ApprovedPortfolioEvent]) -> None:
        kill = envelope.event.kill
        if kill is None or self._kill_seen:
            return
        self._kill_seen = True
        self._alerts.append(kill_alert(kill, envelope.occurred_at, decision=envelope.event.as_of))

    def _on_data_quality(self, envelope: Envelope[DataQualityEvent]) -> None:
        self._issues.append(envelope.event.issue)
        self._issues_at = envelope.occurred_at


def risk_limit_alert(event: RiskEvent, at: datetime) -> Alert | None:
    """The alert for an account rule that reached its limit, or ``None`` for a routine cut."""
    trigger = event.adjustment
    if not isinstance(trigger, AccountTrigger):
        return None
    lines = [
        f"Equity {trigger.equity} at the close of {trigger.at:%Y-%m-%d}, down "
        f"{_percent(trigger.loss)} from {trigger.reference} (limit {_percent(trigger.limit)}).",
        f"Risk profile: {event.profile}.",
    ]
    if trigger.rule is RiskRule.DRAWDOWN_KILL:
        title = "Drawdown kill: trading is halted"
        lines.append(
            "No orders until you run `tyche resume`. Holdings are kept; resting stops stay."
        )
        lines.append(f"Runbook: {KILL_SWITCH_RUNBOOK}")
    else:
        title = "Daily loss limit reached"
        lines.append(
            "No new entries or additions at this close. Exits and reductions still go through."
        )
    return Alert(AlertKind.RISK_LIMIT, title, at, tuple(lines))


def kill_alert(kill: Kill, at: datetime, *, decision: datetime | None = None) -> Alert:
    """The kill switch, as ``tyche kill`` engaged it or as a run's decision found it.

    Args:
        kill: The switch.
        at: When it was engaged, or when the run found it.
        decision: The decision time of the run that found it; ``None`` when the
            command engaging it sends the alert.
    """
    if decision is None:
        title = "Kill switch engaged with flatten" if kill.flatten else "Kill switch engaged"
    else:
        title = f"Kill switch engaged at the decision of {decision:%Y-%m-%d}"
    effect = (
        "Every holding is sold at the next open, each stop cancelled first."
        if kill.flatten
        else "No new orders. Holdings are kept; resting stops stay."
    )
    lines = [
        f"Reason: {kill.reason}",
        effect,
        "Orders already at the broker are not cancelled: see `tyche kill` for the list.",
        f"Only `tyche resume` releases it. Runbook: {KILL_SWITCH_RUNBOOK}",
    ]
    return Alert(AlertKind.KILL_SWITCH, title, at, tuple(lines))


def resumed_alert(
    reason: str,
    at: datetime,
    *,
    released: Kill | None,
    lifted: AccountTrigger | None,
) -> Alert:
    """``tyche resume`` lifted the kill switch, the drawdown halt, or both."""
    what = [
        "the kill switch" if released is not None else "",
        "the drawdown halt" if lifted is not None else "",
    ]
    title = f"Trading resumed: lifted {' and '.join(w for w in what if w)}"
    lines = [f"Reason: {reason}", "The next decision trades normally."]
    if lifted is not None:
        lines.append("The peak is forgotten: the drawdown kill counts from the next close.")
    return Alert(AlertKind.RESUMED, title, at, tuple(lines))


def data_failure_alert(issues: Sequence[DataIssue], at: datetime) -> Alert:
    """Every data problem of one run, in one alert, the first few listed."""
    if not issues:
        raise ValueError("data_failure_alert: needs at least one issue")
    count = len(issues)
    noun = "problem" if count == 1 else "problems"
    lines = [str(issue) for issue in issues[:MAX_ISSUES_LISTED]]
    if count > MAX_ISSUES_LISTED:
        lines.append(f"… and {count - MAX_ISSUES_LISTED} more in the journal.")
    return Alert(AlertKind.DATA_FAILURE, f"Market data: {count} {noun} found", at, tuple(lines))


def run_failed_alert(run_id: str, mode: RunMode, error: str, at: datetime) -> Alert:
    """A run stopped before it finished. ``error`` must already be free of secrets."""
    lines = (
        f"Run {run_id} ({mode}).",
        f"Error: {error}",
        "Nothing more was decided or sent by this run. Check the logs before the next one.",
    )
    return Alert(AlertKind.RUN_FAILED, "A run failed", at, lines)


def channel_check_alert(at: datetime) -> Alert:
    """The message ``tyche notify test`` sends. Nothing happened."""
    return Alert(
        AlertKind.TEST,
        "Tyche can reach this channel",
        at,
        ("A test from `tyche notify test`. Nothing happened in trading.",),
    )


def _percent(fraction: Decimal) -> str:
    return f"{(fraction * 100).quantize(Decimal('0.01'))}%"

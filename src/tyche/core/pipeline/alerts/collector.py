"""Turning events into alerts, and collecting a run's alerts until it ends (ADR-0040).

What is an alert, and what is not:

* **The daily loss limit and the drawdown kill** (an ``AccountTrigger`` on a
  ``RiskEvent``): each is one alert, when it triggers. The approvals that carry the
  drawdown halt afterwards add nothing new.
* **Routine risk cuts are not alerts**: a position shrunk to the profile's size, an
  entry blocked by the position count, a purchase cut to the money caps. A capped
  position is cut at every close, so they belong in the daily summary (PR 16).
* **The kill switch**, once per run, at the first approval that carries it.
* **Reconciliation** (ADR-0044): every mismatch, which halts trading, and every check
  that dropped orders the broker no longer lists. Taking the broker's cash within the
  tolerance is routine, for the daily summary.
* **Data problems**: every ``DataQualityEvent`` of the run, in one alert, so a bad
  download cannot flood the channel.
* **Skipped decisions** (ADR-0043): every ``CycleSkippedEvent`` of the run, in one
  alert, so a catch-up after a week away sends one message, not five.
* **A failed run**, built by the runtime with ``run_failed_alert``, because a run that
  fails cannot publish anything more.
* **What the paper cycle could not do as decided** (ADR-0045), built by the runtime:
  orders lost while sending or not sent (``orders_alert``), and trading still halted
  from an earlier run (``stopped_alert``).
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from tyche.core.domain import (
    AccountTrigger,
    DataIssue,
    Kill,
    Reconciliation,
    ReconciliationStatus,
    RiskRule,
)
from tyche.core.events import (
    ApprovedPortfolioEvent,
    CycleSkippedEvent,
    DataQualityEvent,
    Envelope,
    EventBus,
    ReconciliationEvent,
    RiskEvent,
    RunMode,
    SkipReason,
)
from tyche.core.ports import Alert, AlertKind

SUBSCRIBER = "alerts"

MAX_ISSUES_LISTED = 10
"""Data issues listed one by one in an alert; the rest are counted."""

KILL_SWITCH_RUNBOOK = "docs/runbooks/kill-switch.md"
RECONCILIATION_RUNBOOK = "docs/runbooks/reconciliation-mismatch.md"


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
        self._skipped: list[CycleSkippedEvent] = []
        self._skipped_at: datetime | None = None
        bus.subscribe(RiskEvent, self._on_risk, name=SUBSCRIBER)
        bus.subscribe(ApprovedPortfolioEvent, self._on_approval, name=SUBSCRIBER)
        bus.subscribe(DataQualityEvent, self._on_data_quality, name=SUBSCRIBER)
        bus.subscribe(ReconciliationEvent, self._on_reconciliation, name=SUBSCRIBER)
        bus.subscribe(CycleSkippedEvent, self._on_skipped, name=SUBSCRIBER)

    def alerts(self) -> tuple[Alert, ...]:
        """Every alert so far; then the run's skipped decisions and its data problems,
        each as one alert."""
        collected = list(self._alerts)
        if self._skipped and self._skipped_at is not None:
            collected.append(cycle_skipped_alert(self._skipped, self._skipped_at))
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

    def _on_reconciliation(self, envelope: Envelope[ReconciliationEvent]) -> None:
        alert = reconciliation_alert(envelope.event.reconciliation)
        if alert is not None:
            self._alerts.append(alert)

    def _on_skipped(self, envelope: Envelope[CycleSkippedEvent]) -> None:
        self._skipped.append(envelope.event)
        self._skipped_at = envelope.occurred_at

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


def reconciliation_alert(reconciliation: Reconciliation) -> Alert | None:
    """A mismatch, or orders dropped as ended; ``None`` for a match or adopted cash."""
    if reconciliation.status is ReconciliationStatus.MISMATCH:
        lines = [str(d) for d in reconciliation.differences[:MAX_ISSUES_LISTED]]
        hidden = len(reconciliation.differences) - MAX_ISSUES_LISTED
        if hidden > 0:
            lines.append(f"… and {hidden} more in the journal.")
        lines.extend(
            f"Explained: {fill}. `tyche resume` applies it." for fill in reconciliation.inferred
        )
        lines.extend(f"Ended: {ended}." for ended in reconciliation.ended)
        lines.append(
            "No orders until you run `tyche resume`. Holdings are kept; resting stops stay. "
            "A kill-switch flatten waits: flatten in IBKR's own apps if you must."
        )
        lines.append(f"Runbook: {RECONCILIATION_RUNBOOK}")
        title = "Reconciliation mismatch: trading is halted"
        return Alert(AlertKind.RECONCILIATION, title, reconciliation.at, tuple(lines))
    if not reconciliation.ended:
        return None
    count = len(reconciliation.ended)
    noun = "order" if count == 1 else "orders"
    lines = [f"{ended}." for ended in reconciliation.ended]
    lines.append(
        "No shares moved. Tyche dropped them from its records; the next decision places a "
        "stop again if its sleeve still wants one."
    )
    title = f"Reconciliation: {count} {noun} ended at the broker"
    return Alert(AlertKind.RECONCILIATION, title, reconciliation.at, tuple(lines))


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
    reconciliation: Reconciliation | None = None,
    applied: bool = False,
) -> Alert:
    """``tyche resume`` lifted the kill switch, the drawdown halt, a reconciliation halt."""
    what = [
        "the kill switch" if released is not None else "",
        "the drawdown halt" if lifted is not None else "",
        "the reconciliation halt" if reconciliation is not None else "",
    ]
    named = [w for w in what if w]
    listed = ", ".join(named[:-1]) + " and " + named[-1] if len(named) > 1 else named[0]
    title = f"Trading resumed: lifted {listed}"
    lines = [f"Reason: {reason}", "The next decision trades normally."]
    if lifted is not None:
        lines.append("The peak is forgotten: the drawdown kill counts from the next close.")
    if reconciliation is not None:
        if applied:
            lines.extend(f"Applied: {fill}." for fill in reconciliation.inferred)
            lines.append("Tyche took the broker's cash as the halt recorded it.")
        lines.append("The next run reconciles again first: a difference still there halts again.")
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


def cycle_skipped_alert(skipped: Sequence[CycleSkippedEvent], at: datetime) -> Alert:
    """Every decision a run skipped, in one alert (ADR-0043)."""
    if not skipped:
        raise ValueError("cycle_skipped_alert: needs at least one skipped cycle")
    count = len(skipped)
    noun = "decision" if count == 1 else "decisions"
    lines: list[str] = []
    for event in skipped[:MAX_ISSUES_LISTED]:
        if event.reason is SkipReason.STALE:
            why = f"too late to trade (it could trade until {event.trade_until:%Y-%m-%d %H:%M} UTC)"
        else:
            missing = ", ".join(str(i) for i in event.missing)
            why = f"no bar for {missing}"
        lines.append(f"{event.as_of:%Y-%m-%d}: {why}.")
    if count > MAX_ISSUES_LISTED:
        lines.append(f"… and {count - MAX_ISSUES_LISTED} more in the journal.")
    lines.append(
        "No order was sent for them. Their closes still count: the account rules and the "
        "signals saw every one."
    )
    return Alert(AlertKind.CYCLE_SKIPPED, f"{count} {noun} skipped", at, tuple(lines))


def orders_alert(
    at: datetime,
    *,
    lost: Sequence[str] = (),
    not_sent: Sequence[str] = (),
    foreign_executions: int = 0,
) -> Alert | None:
    """Orders the paper cycle could not send as decided, and executions not Tyche's
    (ADR-0042, ADR-0045); ``None`` when there are none."""
    lines = [
        f"Lost while sending, never resent: {order_id}. The next decision starts from what "
        "the account really holds."
        for order_id in lost
    ]
    lines.extend(
        f"Not sent: {order_id}. IBKR did not confirm the cancellation of the stop on the "
        "same shares in time; the stop stays, and the next decision tries again."
        for order_id in not_sent
    )
    if foreign_executions:
        lines.append(
            f"{foreign_executions} execution(s) today in the account are not Tyche's orders."
        )
    if not lines:
        return None
    return Alert(AlertKind.ORDERS, "Orders not sent as decided", at, tuple(lines))


def stopped_alert(
    at: datetime,
    *,
    halt: AccountTrigger | None,
    unreconciled: Reconciliation | None,
) -> Alert:
    """A paper run started with trading halted by an earlier run (ADR-0045)."""
    lines: list[str] = []
    if halt is not None:
        lines.append(f"Drawdown halt since {halt.at:%Y-%m-%d}: {halt.reason}.")
    if unreconciled is not None:
        count = len(unreconciled.differences) + len(unreconciled.inferred)
        lines.append(
            f"Reconciliation halt since {unreconciled.at:%Y-%m-%d}: {count} difference(s); "
            f"runbook: {RECONCILIATION_RUNBOOK}."
        )
    if not lines:
        raise ValueError("stopped_alert: needs a halt")
    lines.append(
        "This run still reads the broker and every close, but sends no order. Only "
        "`tyche resume` lifts it."
    )
    return Alert(AlertKind.STOPPED, "Trading is still halted", at, tuple(lines))


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

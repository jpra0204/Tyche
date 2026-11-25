"""Alerts: the events Pablo must hear about, turned into messages (ADR-0040).

``AlertCollector`` subscribes to the bus like the journal and keeps the alerts of one
run; the runtime sends them through the ``Notifier`` port once the run has finished.
The other functions build the alerts that do not come from the bus: a command such as
``tyche kill``, or a run that failed.

Pure code: nothing here sends anything, reads a clock or touches a file.
"""

from tyche.core.pipeline.alerts.collector import (
    MAX_ISSUES_LISTED,
    SUBSCRIBER,
    AlertCollector,
    channel_check_alert,
    cycle_skipped_alert,
    data_failure_alert,
    kill_alert,
    orders_alert,
    reconciliation_alert,
    resumed_alert,
    risk_limit_alert,
    run_failed_alert,
    stopped_alert,
)

__all__ = [
    "MAX_ISSUES_LISTED",
    "SUBSCRIBER",
    "AlertCollector",
    "channel_check_alert",
    "cycle_skipped_alert",
    "data_failure_alert",
    "kill_alert",
    "orders_alert",
    "reconciliation_alert",
    "resumed_alert",
    "risk_limit_alert",
    "run_failed_alert",
    "stopped_alert",
]

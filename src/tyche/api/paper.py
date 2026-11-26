"""The Paper page's data, read-only: the last cycle's reconciliations and the alerts
(ADR-0046, console U3). The account, the kill switch and the halts come from the
Status page's reader.

* **Reconciliations** are the ``ReconciliationEvent``\\ s the last paper cycle stored in
  the journal (``state/tyche.db``): one from its check (``paper-<time>-check``) and one
  from its decision (``paper-<time>``), if a session had closed.
* **Alerts** are read from the workspace's logs (``logs/<day>.jsonl``), where every
  alert is written as it is sent, or not sent, and already redacted (ADR-0040). There
  is no other record of them: Discord is the only place they go.

Opening the state database brings its schema up to date, as every command that opens
it does; nothing else is written.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

from tyche.adapters.storage import SqliteJournalStore, StateDatabaseError, open_database
from tyche.api.models import (
    AlertView,
    CashCheckView,
    DifferenceView,
    PaperView,
    ReconciliationView,
)
from tyche.config import Workspace
from tyche.core.domain import Reconciliation
from tyche.core.events import ReconciliationEvent
from tyche.core.ports import JournalStoreError

ALERTS_SHOWN = 50
"""The most alerts the page lists."""

LOG_DAYS_READ = 60
"""How many of the newest daily log files are searched for them."""

_CHECK_RUN = re.compile(r"^paper-\d{8}T\d{6}Z-check$")


def read_paper(workspace: Workspace) -> PaperView:
    """The last paper cycle's reconciliations and the latest alerts."""
    alerts = _alerts(workspace.logs_dir)
    if not workspace.state_database.exists():
        return PaperView(last_cycle=None, reconciliations=[], alerts=alerts)
    try:
        last, found = _last_cycle(workspace.state_database)
    except (StateDatabaseError, JournalStoreError, sqlite3.Error, OSError) as error:
        return PaperView(
            last_cycle=None, reconciliations=[], alerts=alerts, state_unreadable=str(error)
        )
    return PaperView(last_cycle=last, reconciliations=found, alerts=alerts)


def _last_cycle(database: Path) -> tuple[str | None, list[ReconciliationView]]:
    connection = open_database(database)
    try:
        journal = SqliteJournalStore(connection)
        runs = journal.run_ids()
        checks = [run for run in runs if _CHECK_RUN.match(run)]
        if not checks:
            return None, []
        check = checks[-1]
        decision = check.removesuffix("-check")
        found: list[ReconciliationView] = []
        for run_id, stage in ((check, "check"), (decision, "decision")):
            if run_id not in runs:
                continue
            for envelope in journal.read(run_id):
                if isinstance(envelope.event, ReconciliationEvent):
                    found.append(_reconciliation(run_id, stage, envelope.event.reconciliation))
        return check, found
    finally:
        connection.close()


def _reconciliation(run_id: str, stage: str, found: Reconciliation) -> ReconciliationView:
    return ReconciliationView(
        run_id=run_id,
        stage="check" if stage == "check" else "decision",
        at=found.at,
        status=found.status.value,
        differences=[
            DifferenceView(kind=str(d.kind), subject=d.subject, detail=d.detail)
            for d in found.differences
        ],
        inferred=[str(f) for f in found.inferred],
        ended=[str(e) for e in found.ended],
        cash=[
            CashCheckView(
                currency=str(c.currency),
                tyche=str(c.tyche.amount),
                broker_settled=str(c.broker.settled.amount),
                broker_pending=str(c.broker.unsettled.amount),
                accrued=str(c.accrued.amount),
                allowed=str(c.allowed.amount),
                outcome=str(c.outcome),
            )
            for c in found.cash
        ],
    )


def _alerts(logs: Path) -> list[AlertView]:
    """The newest alerts in the logs, newest first. A line that cannot be read is skipped:
    the logs are a record for people, and one bad line must not hide the rest."""
    if not logs.is_dir():
        return []
    files = sorted(logs.glob("*.jsonl"), reverse=True)[:LOG_DAYS_READ]
    found: list[AlertView] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            alert = _alert(line)
            if alert is not None:
                found.append(alert)
                if len(found) == ALERTS_SHOWN:
                    return found
    return found


def _alert(line: str) -> AlertView | None:
    try:
        entry: Any = json.loads(line)
        message = entry["message"]
        if not isinstance(message, str) or not message.startswith("alert") or "title" not in entry:
            return None
        delivery: Literal["sent", "not_sent", "no_channel"]
        if message == "alert sent":
            delivery = "sent"
        elif message == "alert not sent: no notifier":
            delivery = "no_channel"
        else:
            delivery = "not_sent"
        return AlertView(
            at=entry["alert_at"],
            kind=entry["alert"],
            title=entry["title"],
            lines=list(entry.get("lines", [])),
            delivery=delivery,
            error=entry.get("error"),
        )
    except ValueError, KeyError, TypeError:
        return None

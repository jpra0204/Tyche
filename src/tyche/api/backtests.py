"""The Backtests page's data: recorded backtests and their reports, read-only (ADR-0046).

Reads what ``tyche backtest`` wrote in ``reports/backtests/<run id>/``: ``run.json``,
``metrics.json`` and ``report.html``. A record that cannot be read is still listed, with
why, so a half-written or hand-edited folder is seen rather than hidden.
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tyche.api.models import BacktestSummary
from tyche.config import Workspace
from tyche.runtime.report import REPORT_FILE, halt_of

BACKTESTS_FOLDER = "backtests"


class RecordNotFoundError(Exception):
    """No backtest record, or no report in it, by that run id."""


def backtests_dir(workspace: Workspace) -> Path:
    return workspace.reports_dir / BACKTESTS_FOLDER


def list_backtests(workspace: Workspace) -> list[BacktestSummary]:
    """Every recorded backtest, newest first (run ids start with their start time)."""
    folder = backtests_dir(workspace)
    if not folder.is_dir():
        return []
    records = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name)
    return [_summary(record) for record in reversed(records)]


def report_html(workspace: Workspace, run_id: str) -> str:
    """The backtest's ``report.html``, as ``tyche backtest`` or ``tyche report`` wrote it.

    Raises:
        RecordNotFoundError: No record by that id, or it has no report yet.
    """
    record = _record_dir(workspace, run_id)
    report = record / REPORT_FILE
    if not report.is_file():
        raise RecordNotFoundError(f"backtest {run_id} has no report yet; write it with Report")
    return report.read_text(encoding="utf-8")


def _record_dir(workspace: Workspace, run_id: str) -> Path:
    folder = backtests_dir(workspace)
    record = folder / run_id
    if not run_id or Path(run_id).name != run_id or not record.is_dir():
        raise RecordNotFoundError(f"no backtest record named {run_id!r} in {folder}")
    return record


def _summary(record: Path) -> BacktestSummary:
    run_id = record.name
    has_report = (record / REPORT_FILE).is_file()
    try:
        run = _json(record / "run.json")
    except (OSError, ValueError) as error:
        return BacktestSummary(
            run_id=run_id, has_report=has_report, error=f"run.json unreadable: {error}"
        )
    try:
        outcome = run["outcome"]
        starting = run["starting_cash"]
        summary = BacktestSummary(
            run_id=run_id,
            started_at=datetime.fromisoformat(run["started_at"]),
            first=date.fromisoformat(run["range"]["first"]),
            last=date.fromisoformat(run["range"]["last"]),
            risk_profile=run.get("risk", {}).get("profile"),
            currency=starting["currency"],
            starting_cash=starting["amount"],
            final_equity=outcome["final_equity"]["amount"],
            completed=outcome["completed"],
            failure=outcome["failure"],
            halted=halt_of(run) is not None,
            has_report=has_report,
        )
    except (KeyError, TypeError, ValueError) as error:
        return BacktestSummary(
            run_id=run_id, has_report=has_report, error=f"run.json not as expected: {error!r}"
        )
    if outcome.get("metrics") is None:
        return summary
    try:
        metrics = _json(record / outcome["metrics"])
        return summary.model_copy(
            update={
                "total_return": metrics["strategy"]["total_return"],
                "benchmark": metrics["benchmark"]["instrument"],
                "benchmark_total_return": metrics["benchmark"]["total_return"],
                "max_drawdown": (metrics["strategy"]["max_drawdown"] or {}).get("depth"),
            }
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        return summary.model_copy(update={"error": f"metrics.json unreadable: {error!r}"})


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not an object")
    return data

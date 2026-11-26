"""The Research page's data: recorded studies and their reports, read-only (ADR-0046, U4).

A study is a walk-forward, a sweep, a capital analysis or a risk-profile comparison.
Each is a folder in ``reports/<kind's folder>/<id>/`` holding its record file and, once
written, ``report.html``. A record that cannot be read is still listed, with why.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tyche.api.models import CapitalDefaults, ResearchView, StudyKind, StudySummary
from tyche.config import Workspace
from tyche.runtime.capital import (
    DEFAULT_AMOUNTS,
    DEFAULT_POSITIONS,
    DEFAULT_REFERENCE,
    DEFAULT_TOLERANCE,
)
from tyche.runtime.report import REPORT_FILE

FOLDERS: dict[StudyKind, str] = {
    "walk_forward": "walk_forward",
    "sweep": "sweeps",
    "capital": "capital",
    "profiles": "profiles",
}
"""Where each kind is recorded, inside ``reports/``."""

RECORD_FILES: dict[StudyKind, str] = {
    "walk_forward": "walk_forward.json",
    "sweep": "sweep.json",
    "capital": "capital.json",
    "profiles": "profiles.json",
}


class StudyNotFoundError(Exception):
    """No study of that kind by that id, or no report in it yet."""


def read_research(workspace: Workspace) -> ResearchView:
    """The sweeps in ``config/sweeps/``, and ``tyche capital``'s defaults."""
    sweeps_dir = workspace.sweeps_dir
    sweeps = sorted(p.stem for p in sweeps_dir.glob("*.toml")) if sweeps_dir.is_dir() else []
    return ResearchView(
        sweeps=sweeps,
        capital=CapitalDefaults(
            amounts=[str(a) for a in DEFAULT_AMOUNTS],
            reference=str(DEFAULT_REFERENCE),
            tolerance=str(DEFAULT_TOLERANCE * 100),
            positions=DEFAULT_POSITIONS,
        ),
    )


def list_studies(workspace: Workspace, kind: StudyKind) -> list[StudySummary]:
    """Every recorded study of ``kind``, newest first (ids start with their start time)."""
    folder = workspace.reports_dir / FOLDERS[kind]
    if not folder.is_dir():
        return []
    records = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name)
    return [_summary(kind, record) for record in reversed(records)]


def study_report(workspace: Workspace, kind: StudyKind, study_id: str) -> str:
    """The study's ``report.html``.

    Raises:
        StudyNotFoundError: No such study, or it has no report yet.
    """
    folder = workspace.reports_dir / FOLDERS[kind]
    record = folder / study_id
    if not study_id or Path(study_id).name != study_id or not record.is_dir():
        raise StudyNotFoundError(f"no {kind.replace('_', '-')} record named {study_id!r}")
    report = record / REPORT_FILE
    if not report.is_file():
        raise StudyNotFoundError(f"{study_id} has no report yet; write it with Report")
    return report.read_text(encoding="utf-8")


def _summary(kind: StudyKind, record: Path) -> StudySummary:
    has_report = (record / REPORT_FILE).is_file()
    base = StudySummary(kind=kind, study_id=record.name, has_report=has_report)
    try:
        data = _json(record / RECORD_FILES[kind])
    except (OSError, ValueError) as error:
        return base.model_copy(update={"error": f"{RECORD_FILES[kind]} unreadable: {error}"})
    try:
        span = data["range"]
        completed, headline = _HEADLINES[kind](data)
        return base.model_copy(
            update={
                "started_at": datetime.fromisoformat(data["started_at"]),
                "first": date.fromisoformat(span["first"]),
                "last": date.fromisoformat(span["last"]),
                "completed": completed,
                "headline": headline,
            }
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return base.model_copy(update={"error": f"{RECORD_FILES[kind]} not as expected: {error!r}"})


def _walk_forward(data: dict[str, Any]) -> tuple[bool | None, str]:
    outcome = data["outcome"]
    headline = (
        f"{data['scheme']['described']}; "
        f"{outcome['folds_finished']} of {outcome['folds_planned']} folds"
    )
    sweep = data.get("sweep")
    if sweep:
        headline += f"; sweep {sweep['name']} on each training window"
    return bool(outcome["completed"]), headline


def _sweep(data: dict[str, Any]) -> tuple[bool | None, str]:
    outcome = data["outcome"]
    picked = bool(outcome["picked"])
    headline = (
        f"{data['sweep']['name']}: {outcome['trials']} trials, {outcome['measured']} measured; "
        + ("one picked, in-sample" if picked else "nothing picked")
    )
    return picked, headline


def _capital(data: dict[str, Any]) -> tuple[bool | None, str]:
    currency = data["currency"]
    parts = []
    for strategy in data["strategies"]:
        plans = ", ".join(
            f"{plan['plan']} {_amount(plan['minimum_viable'], currency)}"
            for plan in strategy["plans"]
        )
        parts.append(f"{strategy['id']}: {plans}")
    return None, "minimum viable: " + "; ".join(parts)


def _profiles(data: dict[str, Any]) -> tuple[bool | None, str]:
    names = ", ".join(profile["name"] for profile in data["profiles"])
    return bool(data["outcome"]["completed"]), f"profiles: {names}"


def _amount(value: str | None, currency: str) -> str:
    return f"{value} {currency}" if value is not None else "none found"


_HEADLINES: dict[StudyKind, Callable[[dict[str, Any]], tuple[bool | None, str]]] = {
    "walk_forward": _walk_forward,
    "sweep": _sweep,
    "capital": _capital,
    "profiles": _profiles,
}


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not an object")
    return data

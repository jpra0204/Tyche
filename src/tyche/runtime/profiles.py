"""Wiring for ``tyche compare-profiles``: risk profiles side by side (ADR-0036).

Composition-root code (ADR-0004). The configured strategies run as one backtest per
risk profile, over the same days, from the same cache, through the same path as
``tyche backtest`` (``run_and_record``). Only the risk profile changes between runs:
the strategies keep their parameters, so a comparison adds no trial to any plugin's
count (ADR-0030). Nothing is picked: which profile to trade is Pablo's choice, and the
report warns that choosing on these in-sample results is a selection too.

Everything goes to ``reports/profiles/<id>/`` in the workspace:

* ``profiles.json``: what ran (code, range, strategies, benchmark), and for each
  profile its values, its config hash, its run's folder and how the run ended.
* ``runs/<profile>/``: each profile's full backtest record, as ``tyche backtest``
  writes it, without a report of its own.
* ``report.html``: every profile side by side, against the benchmark.
"""

import json
import platform
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tyche.adapters.clocks import SystemClock
from tyche.config import TycheConfig, Workspace, load_config
from tyche.core.ports import Clock
from tyche.runtime.backtest import (
    BENCHMARK_METHOD,
    BacktestOutcome,
    BacktestRequestError,
    CodeVersion,
    cached_market,
    checked_range,
    current_code_version,
    new_run_id,
    risk_record,
    run_and_record,
)
from tyche.runtime.strategies import build_strategies

PROFILES_FORMAT = 1
"""Version of ``profiles.json``'s layout. Raised when a field changes meaning or goes away."""

PROFILES_FILE = "profiles.json"

RUNS_FOLDER = "runs"
"""Where each profile's backtest record goes, inside the comparison's folder."""


@dataclass(frozen=True, slots=True)
class ProfileRun:
    """One profile's backtest, recorded."""

    profile: str
    config: TycheConfig
    outcome: BacktestOutcome


@dataclass(frozen=True, slots=True)
class ProfilesOutcome:
    """A finished comparison and where its record was written."""

    comparison_id: str
    folder: Path
    code: CodeVersion
    first: date
    last: date
    runs: tuple[ProfileRun, ...]


Progress = Callable[[ProfileRun], None]
"""Told about each profile's run as soon as it is recorded, for the command to print."""


def chosen_profiles(workspace: Workspace, names: Sequence[str]) -> tuple[TycheConfig, ...]:
    """The workspace's configuration under each profile in ``names``, or under every
    profile in ``config/risk/`` when ``names`` is empty.

    Raises:
        ConfigError: The configuration, or a named profile, is not valid.
        BacktestRequestError: Fewer than two profiles, or one named twice.
    """
    if len(set(names)) != len(names):
        raise BacktestRequestError("each risk profile may be named once")
    first = load_config(workspace, names[0]) if names else load_config(workspace)
    names = tuple(names) or first.risk_profiles
    if len(names) < 2:
        raise BacktestRequestError(
            "comparing needs at least two risk profiles; the workspace has "
            f"{', '.join(first.risk_profiles)} in config/risk/"
        )
    return tuple(
        first if first.risk_profile.name == name else load_config(workspace, name) for name in names
    )


def run_profile_comparison(
    configs: Sequence[TycheConfig],
    first: date,
    last: date | None = None,
    *,
    clock: Clock | None = None,
    code: CodeVersion | None = None,
    progress: Progress | None = None,
) -> ProfilesOutcome:
    """Backtest the configured strategies once under each configuration's risk profile,
    over the same days, and record every run and the comparison.

    Raises:
        BacktestRequestError: The range cannot be run as asked, or history is missing
            from the cache. Profiles already run stay recorded, and so does the
            comparison, as stopped.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: A run cannot be set up.
        ConfigError: A strategy cannot be built from its file.
    """
    clock = clock or SystemClock()
    code = code or current_code_version()
    base = configs[0]
    last = checked_range(base, first, last)
    for config in configs:
        build_strategies(config)  # a bad strategy file fails before anything is written
    market = cached_market(base, last, clock)
    root = base.workspace.reports_dir / "profiles"
    comparison_id = new_run_id(root, clock.now(), base.config_hash)
    folder = root / comparison_id
    started = clock.now()

    runs: list[ProfileRun] = []
    try:
        for config in configs:
            name = config.risk_profile.name
            outcome = run_and_record(
                config,
                market,
                build_strategies(config),
                run_id=f"{comparison_id}-{name}",
                first=first,
                last=last,
                folder=folder / RUNS_FOLDER / name,
                clock=clock,
                code=code,
                part_of={"profile_comparison": comparison_id, "profile": name},
            )
            run = ProfileRun(name, config, outcome)
            runs.append(run)
            if progress is not None:
                progress(run)
    except BacktestRequestError as error:
        if folder.exists():
            _write_json(
                folder / PROFILES_FILE,
                profiles_record(
                    comparison_id,
                    configs,
                    runs,
                    first,
                    last,
                    code,
                    started,
                    clock.now(),
                    stopped=str(error),
                ),
            )
        raise

    folder.mkdir(parents=True, exist_ok=True)
    record = profiles_record(comparison_id, configs, runs, first, last, code, started, clock.now())
    _write_json(folder / PROFILES_FILE, record)
    return ProfilesOutcome(comparison_id, folder, code, first, last, tuple(runs))


def profiles_record(
    comparison_id: str,
    configs: Sequence[TycheConfig],
    runs: Sequence[ProfileRun],
    first: date,
    last: date,
    code: CodeVersion,
    started: datetime,
    finished: datetime,
    *,
    stopped: str | None = None,
) -> dict[str, Any]:
    """``profiles.json``: what ran, profile by profile, and how each run ended."""
    base = configs[0]
    done = {run.profile: run for run in runs}
    plugins = {s.strategy_id: s.plugin for s in base.strategies}
    return {
        "profiles_format": PROFILES_FORMAT,
        "comparison_id": comparison_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "code": {
            "tyche_version": code.tyche,
            "git_commit": code.commit,
            "git_dirty": code.dirty,
            "python": platform.python_version(),
        },
        "market_profile": base.market_profile.name,
        "range": {"first": first.isoformat(), "last": last.isoformat()},
        "holdout_starts": base.backtest.holdout_starts.isoformat(),
        "starting_cash": {
            "amount": str(base.backtest.starting_cash.amount),
            "currency": base.backtest.starting_cash.currency.value,
        },
        "strategies": [
            {"id": strategy_id, "plugin": plugins.get(strategy_id), "budget": str(budget)}
            for strategy_id, budget in sorted(base.budgets.items())
        ],
        "benchmark": {
            "instrument": str(base.market_profile.benchmark),
            "method": BENCHMARK_METHOD,
        },
        "trials_added": 0,
        "profiles": [
            _profile_record(config, done.get(config.risk_profile.name)) for config in configs
        ],
        "outcome": {
            "completed": stopped is None,
            "failure": stopped,
            "profiles_planned": len(configs),
            "profiles_run": len(runs),
        },
    }


def _profile_record(config: TycheConfig, run: ProfileRun | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": config.risk_profile.name,
        "config_hash": config.config_hash,
        "risk": risk_record(config.risk_limits),
        "run": None,
    }
    if run is not None:
        outcome = run.outcome
        record["run"] = {
            "run_id": outcome.run_id,
            "folder": f"{RUNS_FOLDER}/{run.profile}",
            "completed": outcome.result.run.completed,
            "failure": outcome.result.run.failure,
            "measured": outcome.metrics is not None,
            "metrics_error": outcome.metrics_error,
        }
    return record


def is_profile_comparison(folder: Path) -> bool:
    """True if ``folder`` holds a risk-profile comparison's record."""
    return (folder / PROFILES_FILE).is_file()


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

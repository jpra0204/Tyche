"""Counting trials: every distinct set of parameters a plugin has ever run with (ADR-0030).

Composition-root code (ADR-0004). It reads the workspace's records, never the cache,
and fingerprints each strategy a record ran with ``trial_key``: the plugin, its
version and its full parameters. Running the same trial again adds nothing; changing
any parameter, or the plugin's rules (its version), is a new trial.

Where trials are found, anywhere under ``reports/``:

* every ``run.json``: a backtest, a walk-forward's window, a sweep's pick. Each
  strategy in it is a trial. Records written before parameter sweeps do not state the
  parameters; their config snapshot holds the strategy file they were built from.
* every ``trials.json``: a sweep, alone or on a walk-forward's training window. Each
  combination in it is a trial, whether or not it was the pick.

A record Tyche cannot read stops the count with an error rather than being skipped: a
count that quietly drops trials would make every deflated result look better.
"""

import json
from pathlib import Path
from typing import Any

from tyche.core.backtest import trial_key

TRIALS_FILE = "trials.json"
"""Every combination of one sweep, with its parameters and results."""


class TrialCountError(ValueError):
    """A record under ``reports/`` cannot be read, so trials cannot be counted."""


def recorded_trial_keys(reports_dir: Path, plugin: str) -> frozenset[str]:
    """Every trial of ``plugin`` recorded under ``reports_dir``, as ``trial_key``s.

    Raises:
        TrialCountError: A ``run.json`` or ``trials.json`` cannot be read.
    """
    keys: set[str] = set()
    if not reports_dir.is_dir():
        return frozenset()
    for path in sorted(reports_dir.rglob("run.json")):
        try:
            keys.update(_from_run(_read(path), plugin, path))
        except (KeyError, TypeError, AttributeError) as error:
            raise TrialCountError(f"{path}: cannot count its trials: {error!r}") from None
    for path in sorted(reports_dir.rglob(TRIALS_FILE)):
        record = _read(path)
        if record.get("plugin") != plugin:
            continue
        try:
            keys.update(str(trial["key"]) for trial in record["trials"])
        except (KeyError, TypeError) as error:
            raise TrialCountError(f"{path}: cannot count its trials: {error!r}") from None
    return frozenset(keys)


def _from_run(record: dict[str, Any], plugin: str, path: Path) -> set[str]:
    keys: set[str] = set()
    snapshot = record.get("config", {})
    for strategy in record.get("strategies", []):
        if strategy.get("plugin") != plugin:
            continue
        parameters = strategy.get("parameters")
        if parameters is None:
            file = snapshot.get(f"config/strategies/{strategy['id']}.toml")
            if file is None:
                raise TrialCountError(
                    f"{path}: strategy {strategy['id']!r} states no parameters and its "
                    "file is not in the config snapshot"
                )
            parameters = file.get("parameters", {})
        keys.add(trial_key(plugin, strategy["version"], parameters))
    return keys


def _read(path: Path) -> dict[str, Any]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TrialCountError(f"{path}: cannot read it to count trials: {error}") from None
    if not isinstance(content, dict):
        raise TrialCountError(f"{path}: cannot read it to count trials: not a JSON object")
    return content

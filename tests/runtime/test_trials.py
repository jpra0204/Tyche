"""Counting trials from the records under ``reports/`` (ADR-0030)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tyche.core.backtest import trial_key
from tyche.runtime.trials import TrialCountError, recorded_trial_keys

ROTATION = {"holdings": 3, "momentum_sessions": 126}


def write(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def run_record(*strategies: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"strategies": list(strategies), "config": config or {}}


def rotation(parameters: dict[str, Any] | None = None, version: str = "1") -> dict[str, Any]:
    entry: dict[str, Any] = {"id": "trend_rotation", "plugin": "trend_rotation", "version": version}
    if parameters is not None:
        entry["parameters"] = parameters
    return entry


class TestCountingTrials:
    def test_no_reports_folder_means_no_trial(self, tmp_path: Path) -> None:
        assert recorded_trial_keys(tmp_path / "reports", "trend_rotation") == frozenset()

    def test_each_run_records_a_trial_of_each_strategy(self, tmp_path: Path) -> None:
        holding = {"id": "buy_and_hold", "plugin": "buy_and_hold", "version": "1", "parameters": {}}
        write(tmp_path / "backtests/a/run.json", run_record(rotation(ROTATION), holding))

        assert recorded_trial_keys(tmp_path, "trend_rotation") == {
            trial_key("trend_rotation", "1", ROTATION)
        }
        assert recorded_trial_keys(tmp_path, "buy_and_hold") == {trial_key("buy_and_hold", "1", {})}

    def test_the_same_trial_run_twice_is_counted_once(self, tmp_path: Path) -> None:
        write(tmp_path / "backtests/a/run.json", run_record(rotation(ROTATION)))
        write(tmp_path / "walk_forward/w/folds/01-test/run.json", run_record(rotation(ROTATION)))

        assert len(recorded_trial_keys(tmp_path, "trend_rotation")) == 1

    def test_a_new_version_or_parameter_is_a_new_trial(self, tmp_path: Path) -> None:
        write(tmp_path / "backtests/a/run.json", run_record(rotation(ROTATION)))
        write(tmp_path / "backtests/b/run.json", run_record(rotation(ROTATION, version="2")))
        write(
            tmp_path / "backtests/c/run.json",
            run_record(rotation({**ROTATION, "holdings": 2})),
        )

        assert len(recorded_trial_keys(tmp_path, "trend_rotation")) == 3

    def test_records_from_before_sweeps_give_their_parameters_in_the_snapshot(
        self, tmp_path: Path
    ) -> None:
        snapshot = {
            "config/strategies/trend_rotation.toml": {
                "plugin": "trend_rotation",
                "parameters": ROTATION,
            }
        }
        write(tmp_path / "backtests/old/run.json", run_record(rotation(), config=snapshot))

        assert recorded_trial_keys(tmp_path, "trend_rotation") == {
            trial_key("trend_rotation", "1", ROTATION)
        }

    def test_every_combination_of_a_sweep_counts(self, tmp_path: Path) -> None:
        trials = {"plugin": "trend_rotation", "trials": [{"key": "k1"}, {"key": "k2"}]}
        write(tmp_path / "sweeps/s/trials.json", trials)
        write(tmp_path / "sweeps/other/trials.json", {"plugin": "mean_reversion", "trials": []})

        assert recorded_trial_keys(tmp_path, "trend_rotation") == {"k1", "k2"}

    def test_an_unreadable_record_stops_the_count(self, tmp_path: Path) -> None:
        (tmp_path / "backtests/a").mkdir(parents=True)
        (tmp_path / "backtests/a/run.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(TrialCountError, match="cannot read it"):
            recorded_trial_keys(tmp_path, "trend_rotation")

    def test_a_record_missing_its_parameters_stops_the_count(self, tmp_path: Path) -> None:
        write(tmp_path / "backtests/a/run.json", run_record(rotation()))

        with pytest.raises(TrialCountError, match="states no parameters"):
            recorded_trial_keys(tmp_path, "trend_rotation")

    def test_a_malformed_trials_file_stops_the_count(self, tmp_path: Path) -> None:
        write(tmp_path / "sweeps/s/trials.json", {"plugin": "trend_rotation", "trials": [{}]})

        with pytest.raises(TrialCountError, match="cannot count"):
            recorded_trial_keys(tmp_path, "trend_rotation")

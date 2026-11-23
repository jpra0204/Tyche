"""``tyche compare-profiles``: risk profiles side by side (ADR-0036).

Uses the scripted workspace of ``test_backtest``: SPY and QQQ in late 2023,
buy-and-hold on SPY, under ``default`` and a ``wide`` profile that allows 25% a position.
"""

import json
from pathlib import Path

import pytest

from tests.runtime.test_backtest import CODE, FIRST, LAST, NOW
from tests.runtime.test_backtest import config as config  # the fixture
from tyche.adapters.reports import render_html
from tyche.config import TycheConfig
from tyche.runtime.backtest import BacktestRequestError
from tyche.runtime.profiles import (
    PROFILES_FILE,
    ProfileRun,
    ProfilesOutcome,
    chosen_profiles,
    is_profile_comparison,
    run_profile_comparison,
)
from tyche.runtime.profiles_report import (
    profiles_report,
    read_comparison,
    write_profiles_report,
)
from tyche.runtime.report import ReportError, halts_callout
from tyche.runtime.trials import recorded_trial_keys


def add_wide(config: TycheConfig) -> None:
    risk = config.workspace.root / "config" / "risk"
    wide = (risk / "default.toml").read_text().replace('"0.20"', '"0.25"')
    (risk / "wide.toml").write_text(wide)


def compare(config: TycheConfig, *names: str) -> ProfilesOutcome:
    add_wide(config)
    configs = chosen_profiles(config.workspace, names)
    return run_profile_comparison(configs, FIRST, LAST, clock=NOW, code=CODE)


class TestChoosingProfiles:
    def test_every_profile_in_the_workspace_by_default(self, config: TycheConfig) -> None:
        add_wide(config)
        configs = chosen_profiles(config.workspace, ())
        assert [c.risk_profile.name for c in configs] == ["default", "wide"]
        assert configs[0].config_hash != configs[1].config_hash

    def test_the_profiles_named_in_their_order(self, config: TycheConfig) -> None:
        add_wide(config)
        configs = chosen_profiles(config.workspace, ("wide", "default"))
        assert [c.risk_profile.name for c in configs] == ["wide", "default"]

    def test_needs_two_profiles(self, config: TycheConfig) -> None:
        with pytest.raises(BacktestRequestError, match="at least two risk profiles"):
            chosen_profiles(config.workspace, ())

    def test_refuses_a_profile_named_twice(self, config: TycheConfig) -> None:
        with pytest.raises(BacktestRequestError, match="named once"):
            chosen_profiles(config.workspace, ("default", "default"))


class TestTheComparison:
    def test_runs_each_profile_over_the_same_days(self, config: TycheConfig) -> None:
        outcome = compare(config)

        assert [r.profile for r in outcome.runs] == ["default", "wide"]
        days = {(r.outcome.first, r.outcome.last) for r in outcome.runs}
        assert days == {(FIRST, LAST)}
        # buy_and_hold wants all of SPY; each profile caps it at its own size.
        held = [
            r.outcome.result.account.position(r.outcome.result.fills[0].instrument)
            for r in outcome.runs
        ]
        assert held[0] is not None
        assert held[1] is not None
        assert held[0].quantity < held[1].quantity

    def test_records_every_run_and_the_comparison(self, config: TycheConfig) -> None:
        outcome = compare(config)

        assert is_profile_comparison(outcome.folder)
        assert outcome.folder.parent == config.workspace.reports_dir / "profiles"
        study = json.loads((outcome.folder / PROFILES_FILE).read_text())
        assert study["comparison_id"] == outcome.comparison_id
        assert study["trials_added"] == 0
        assert study["outcome"] == {
            "completed": True,
            "failure": None,
            "profiles_planned": 2,
            "profiles_run": 2,
        }
        [default, wide] = study["profiles"]
        assert (default["name"], wide["name"]) == ("default", "wide")
        assert wide["risk"]["max_position_size"] == "0.25"
        assert wide["run"]["folder"] == "runs/wide"
        run = json.loads((outcome.folder / "runs" / "wide" / "run.json").read_text())
        assert run["part_of"] == {"profile_comparison": outcome.comparison_id, "profile": "wide"}
        assert run["risk"]["profile"] == "wide"
        assert run["config_hash"] == wide["config_hash"]

    def test_adds_no_trial(self, config: TycheConfig) -> None:
        reports = config.workspace.reports_dir
        compare(config)
        assert len(recorded_trial_keys(reports, "buy_and_hold")) == 1

    def test_tells_progress_about_each_profile(self, config: TycheConfig) -> None:
        add_wide(config)
        seen: list[ProfileRun] = []
        configs = chosen_profiles(config.workspace, ())
        run_profile_comparison(configs, FIRST, LAST, clock=NOW, code=CODE, progress=seen.append)
        assert [r.profile for r in seen] == ["default", "wide"]


class TestTheReport:
    def test_shows_every_profile_side_by_side_and_names_no_best(self, config: TycheConfig) -> None:
        outcome = compare(config)

        page = write_profiles_report(outcome.folder).read_text(encoding="utf-8")

        for title in (
            "Side by side",
            "What each profile&#x27;s limits did",
            "What ran",
            "Data and its limits",
        ):
            assert f"<h2>{title}</h2>" in page
        assert '<th class="num">default</th>' in page
        assert '<th class="num">wide</th>' in page
        assert "This report names no best profile." in page
        assert "2 profiles were compared. Choosing the one that looks best here is a selection" in (
            page
        )
        assert page.count('<figure class="chart">') == 2
        assert "The drawdown kill halted" not in page
        assert " halted<" not in page

    def test_says_when_and_how_late_a_profile_halted(self, config: TycheConfig) -> None:
        outcome = compare(config)
        path = outcome.folder / "runs" / "wide" / "run.json"
        run = json.loads(path.read_text())
        run["outcome"]["account_rules"]["halt"] = {
            "at": "2023-12-01T21:00:00+00:00",
            "peak": {"amount": "10100", "currency": "USD"},
            "equity": {"amount": "8500", "currency": "USD"},
            "drawdown": "0.158416",
            "limit": "0.15",
        }
        path.write_text(json.dumps(run))

        page = render_html(profiles_report(read_comparison(outcome.folder)))

        assert "The drawdown kill halted wide on 2023-12-01, 15.84% below its peak" in page
        assert "of the range still to run" in page
        assert "2023-12-01 (" in page
        assert page.count(">wide halted<") == 2

    def test_refuses_a_folder_that_is_not_a_comparison(self, tmp_path: Path) -> None:
        with pytest.raises(ReportError, match="is not a risk-profile comparison"):
            read_comparison(tmp_path)


class TestHaltsCallout:
    def test_names_every_halted_run(self) -> None:
        callout = halts_callout(["trial 4 (2006-06-13)", "trial 9 (2008-10-09)"], "27 trials")
        assert callout is not None
        assert callout.text.startswith(
            "The drawdown kill halted 2 of 27 trials: trial 4 (2006-06-13), trial 9 (2008-10-09)."
        )

    def test_says_nothing_when_none_halted(self) -> None:
        assert halts_callout([], "27 trials") is None

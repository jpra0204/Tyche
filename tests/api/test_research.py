"""The Research page (ADR-0046, console U4): walk-forward, sweeps, capital and profile
comparisons started from the page, and their records and reports.

Records are made in-process with the runtime tests' own helpers, which are quicker than
a subprocess; one profile comparison runs as the real `tyche compare-profiles`, end to
end.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.api.test_app import TOKEN, client
from tests.api.test_runs import console, finished
from tests.runtime.test_backtest import LAST
from tests.runtime.test_backtest import config as config  # the fixture: SPY and QQQ cached
from tests.runtime.test_capital import analysed as analysed  # module fixture
from tests.runtime.test_profiles import add_wide, compare
from tests.runtime.test_sweep import swept as swept  # module fixture
from tests.runtime.test_walk_forward import walked as walked  # module fixture
from tyche.api import create_app
from tyche.api.models import (
    CapitalRunRequest,
    CompareProfilesRequest,
    SweepRequest,
    WalkForwardRequest,
)
from tyche.api.runs import arguments
from tyche.config import TycheConfig, Workspace, init_workspace
from tyche.runtime.capital import CapitalOutcome
from tyche.runtime.capital_report import write_capital_report
from tyche.runtime.profiles_report import write_profiles_report
from tyche.runtime.sweep import SweepOutcome
from tyche.runtime.sweep_report import write_sweep_report
from tyche.runtime.walk_forward import WalkForwardOutcome
from tyche.runtime.walk_forward_report import write_walk_forward_report

FIRST = date(2005, 1, 3)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def workspace_of(record_dir: Path) -> Workspace:
    """The workspace a record folder sits in: ``<root>/reports/<kind>/<id>``."""
    return Workspace(record_dir.parents[2])


def studies(workspace: Workspace, kind: str) -> list[dict[str, Any]]:
    response = client(create_app(workspace, TOKEN, environ={})).get(f"/api/studies/{kind}")
    assert response.status_code == 200
    body: list[dict[str, Any]] = response.json()
    return body


class TestArguments:
    def test_walk_forward_with_every_option(self) -> None:
        request = WalkForwardRequest(
            command="walk_forward",
            first=FIRST,
            last=date(2023, 12, 29),
            train_years=3,
            test_years=2,
            rolling=True,
            sweep="trend_rotation",
            risk_profile="stage-1",
        )

        assert arguments(request) == [
            "walk-forward",
            "--from",
            "2005-01-03",
            "--to",
            "2023-12-29",
            "--train-years",
            "3",
            "--test-years",
            "2",
            "--rolling",
            "--sweep",
            "trend_rotation",
            "--risk-profile",
            "stage-1",
        ]

    def test_walk_forward_with_its_defaults(self) -> None:
        request = WalkForwardRequest(command="walk_forward", first=FIRST)

        assert arguments(request) == [
            "walk-forward",
            "--from",
            "2005-01-03",
            "--train-years",
            "5",
            "--test-years",
            "1",
            "--risk-profile",
            "default",
        ]

    def test_sweep(self) -> None:
        request = SweepRequest(command="sweep", name="trend_rotation", first=FIRST)

        assert arguments(request) == [
            "sweep",
            "trend_rotation",
            "--from",
            "2005-01-03",
            "--risk-profile",
            "default",
        ]

    def test_capital_leaves_out_what_was_left_empty(self) -> None:
        request = CapitalRunRequest(command="capital", first=FIRST)

        assert arguments(request) == [
            "capital",
            "--from",
            "2005-01-03",
            "--risk-profile",
            "default",
        ]

    def test_capital_with_every_option(self) -> None:
        request = CapitalRunRequest(
            command="capital",
            first=FIRST,
            amounts=["1000", "5000.50"],
            reference="100000",
            tolerance="0.5",
            positions=2,
            risk_profile="stage-2",
        )

        assert arguments(request) == [
            "capital",
            "--from",
            "2005-01-03",
            "--amounts",
            "1000,5000.50",
            "--reference",
            "100000",
            "--tolerance",
            "0.5",
            "--positions",
            "2",
            "--risk-profile",
            "stage-2",
        ]

    def test_compare_profiles_names_each(self) -> None:
        request = CompareProfilesRequest(
            command="compare_profiles", first=FIRST, risk_profiles=["stage-1", "stage-2"]
        )

        assert arguments(request) == [
            "compare-profiles",
            "--from",
            "2005-01-03",
            "--risk-profile",
            "stage-1",
            "--risk-profile",
            "stage-2",
        ]

    def test_compare_profiles_without_names_compares_every_one(self) -> None:
        request = CompareProfilesRequest(command="compare_profiles", first=FIRST)

        assert arguments(request) == ["compare-profiles", "--from", "2005-01-03"]


class TestRefused:
    @pytest.mark.parametrize(
        "request_body",
        [
            pytest.param(
                {"command": "walk_forward", "first": "2005-01-03", "train_years": 0},
                id="no training years",
            ),
            pytest.param(
                {"command": "walk_forward", "first": "2005-01-03", "sweep": "--rolling"},
                id="a sweep that is an option",
            ),
            pytest.param({"command": "sweep", "first": "2005-01-03"}, id="a sweep with no name"),
            pytest.param(
                {"command": "sweep", "name": "../x", "first": "2005-01-03"},
                id="a sweep name that is a path",
            ),
            pytest.param(
                {"command": "capital", "first": "2005-01-03", "amounts": ["-500"]},
                id="a negative amount",
            ),
            pytest.param(
                {"command": "capital", "first": "2005-01-03", "amounts": ["1e5"]},
                id="an amount in another notation",
            ),
            pytest.param(
                {"command": "capital", "first": "2005-01-03", "tolerance": "half"},
                id="a tolerance in words",
            ),
            pytest.param(
                {"command": "capital", "first": "2005-01-03", "positions": 0},
                id="no positions",
            ),
            pytest.param(
                {"command": "compare_profiles", "first": "2005-01-03", "risk_profiles": ["-x"]},
                id="a profile that is an option",
            ),
            pytest.param(
                {"command": "compare_profiles", "first": "2005-01-03", "best": True},
                id="a field the command does not have",
            ),
        ],
    )
    def test_before_a_process_starts(
        self, workspace: Workspace, request_body: dict[str, Any]
    ) -> None:
        test_client = client(console(workspace))

        response = test_client.post("/api/runs", json=request_body)

        assert response.status_code == 422
        assert test_client.get("/api/runs/current").json() is None


class TestResearchView:
    def test_the_sweeps_and_the_capital_defaults(self, workspace: Workspace) -> None:
        body = client(create_app(workspace, TOKEN, environ={})).get("/api/research").json()

        assert body["sweeps"] == ["trend_rotation"]
        assert body["capital"] == {
            "amounts": ["500", "1000", "2000", "5000", "10000", "25000"],
            "reference": "100000",
            "tolerance": "0.500",
            "positions": 5,
        }


class TestStudies:
    def test_none_yet(self, workspace: Workspace) -> None:
        for kind in ("walk_forward", "sweep", "capital", "profiles"):
            assert studies(workspace, kind) == []

    def test_an_unknown_kind_is_refused(self, workspace: Workspace) -> None:
        response = client(create_app(workspace, TOKEN, environ={})).get("/api/studies/paper")

        assert response.status_code == 422

    def test_a_walk_forward(self, walked: WalkForwardOutcome) -> None:
        workspace = workspace_of(walked.record_dir)

        [summary] = studies(workspace, "walk_forward")

        assert summary["study_id"] == walked.record_dir.name
        assert summary["completed"] is True
        assert "folds" in summary["headline"]
        assert summary["error"] is None

    def test_a_sweep(self, swept: SweepOutcome) -> None:
        workspace = workspace_of(swept.record_dir)

        summaries = studies(workspace, "sweep")

        summary = next(s for s in summaries if s["study_id"] == swept.record_dir.name)
        assert summary["completed"] is True
        assert summary["headline"].startswith("small: ")
        assert "one picked, in-sample" in summary["headline"]

    def test_a_capital_analysis(self, analysed: CapitalOutcome) -> None:
        workspace = workspace_of(analysed.record_dir)

        [summary] = studies(workspace, "capital")

        assert summary["completed"] is None
        assert summary["headline"].startswith("minimum viable: ")

    def test_a_profile_comparison_and_its_report(self, config: TycheConfig) -> None:
        outcome = compare(config)
        write_profiles_report(outcome.folder)
        test_client = client(create_app(config.workspace, TOKEN, environ={}))

        [summary] = test_client.get("/api/studies/profiles").json()

        assert summary["headline"] == "profiles: default, wide"
        assert summary["has_report"] is True
        report = test_client.get(f"/api/studies/profiles/{summary['study_id']}/report")
        assert report.status_code == 200
        assert report.headers["content-security-policy"] == "sandbox"
        assert report.text == (outcome.folder / "report.html").read_text()

    def test_each_kind_s_report(
        self, walked: WalkForwardOutcome, swept: SweepOutcome, analysed: CapitalOutcome
    ) -> None:
        for kind, folder, write in (
            ("walk_forward", walked.record_dir, write_walk_forward_report),
            ("sweep", swept.record_dir, write_sweep_report),
            ("capital", analysed.record_dir, write_capital_report),
        ):
            write(folder)
            test_client = client(create_app(workspace_of(folder), TOKEN, environ={}))

            response = test_client.get(f"/api/studies/{kind}/{folder.name}/report")

            assert response.status_code == 200, kind

    def test_a_study_without_a_report_says_so(self, workspace: Workspace) -> None:
        folder = workspace.reports_dir / "capital" / "20240101T000000Z-aaaaaaaa"
        folder.mkdir(parents=True)
        test_client = client(create_app(workspace, TOKEN, environ={}))

        response = test_client.get(f"/api/studies/capital/{folder.name}/report")

        assert response.status_code == 404
        assert "no report yet" in response.json()["detail"]

    def test_a_broken_record_is_listed_with_why(self, workspace: Workspace) -> None:
        folder = workspace.reports_dir / "sweeps" / "20240101T000000Z-aaaaaaaa"
        folder.mkdir(parents=True)
        (folder / "sweep.json").write_text('{"range": {}}')

        [summary] = studies(workspace, "sweep")

        assert "not as expected" in summary["error"]


def test_a_real_profile_comparison_from_the_page(config: TycheConfig) -> None:
    add_wide(config)
    test_client = client(create_app(config.workspace, TOKEN, environ={}))

    started = test_client.post(
        "/api/runs",
        json={
            "command": "compare_profiles",
            "first": "2023-11-01",
            "last": LAST.isoformat(),
            "risk_profiles": ["default", "wide"],
        },
    )

    assert started.status_code == 201
    run = finished(test_client, timeout=120)
    assert run["state"] == "succeeded", run["lines"]
    [summary] = test_client.get("/api/studies/profiles").json()
    assert summary["headline"] == "profiles: default, wide"
    assert summary["has_report"] is True

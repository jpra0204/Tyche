"""``tyche walk-forward``'s wiring: folds of backtests in, a record and a report out.

The cache is filled the way `tyche data fetch` fills it, from scripted Yahoo answers,
for SPY and QQQ from October 2019 to the end of 2023. The workspace runs its template
strategy, buy-and-hold on SPY. Most tests read one walk-forward, run once: two folds,
training on 2020 to 2021 and testing 2022, then training on 2020 to 2022 and testing
2023.
"""

import csv
import json
import math
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.workspace import keep_candidates
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import YFinanceSource
from tyche.adapters.reports import Table
from tyche.config import TycheConfig, Workspace, init_workspace, load_config
from tyche.core.backtest import FoldScheme, HoldoutError, MetricsError, WalkForwardError
from tyche.core.domain import AssetClass
from tyche.core.sim import SimClock
from tyche.runtime import walk_forward as runtime_walk_forward
from tyche.runtime.backtest import (
    BacktestOutcome,
    BacktestRequestError,
    CodeVersion,
    run_and_record,
)
from tyche.runtime.data import CALENDAR_START, fetch_daily_histories, instrument_for
from tyche.runtime.report import REPORT_FILE, ReportError
from tyche.runtime.walk_forward import (
    WALK_FORWARD_FILE,
    WalkForwardOutcome,
    run_configured_walk_forward,
)
from tyche.runtime.walk_forward_report import (
    read_walk_forward,
    walk_forward_report,
    write_walk_forward_report,
)

NYSE = ExchangeCalendarsCalendar("XNYS", first=CALENDAR_START, last=date(2024, 3, 31))
CACHED_FROM, CACHED_TO = date(2019, 10, 1), date(2023, 12, 29)
FIRST, LAST = date(2020, 1, 2), date(2023, 12, 29)
SCHEME = FoldScheme(train_years=2, test_years=1)
NOW = SimClock(datetime(2024, 1, 5, 12, 0, tzinfo=UTC))
CODE = CodeVersion("0.0.0", "0123456789abcdef0123", dirty=False)


def workspace(root: Path, cached_to: date = CACHED_TO) -> TycheConfig:
    home = root / "home"
    home.mkdir()
    keep_candidates(init_workspace(home / "ws", user_home=home).root, "SPY", "QQQ")
    config = load_config(Workspace(home / "ws"))
    profile = config.market_profile
    days = [s.day for s in NYSE.sessions_between(CACHED_FROM, cached_to)]
    # SPY rises and falls in waves, so some test windows beat a flat benchmark and some
    # do not; QQQ is flat.
    spy = [row(d, 300 + i * 0.05 + 25 * math.sin(i / 40)) for i, d in enumerate(days)]
    fetch = FakeFetch(spy, [row(d, 350) for d in days])
    outcomes = fetch_daily_histories(
        config,
        [
            instrument_for("SPY", "ARCX", AssetClass.ETF, profile),
            instrument_for("QQQ", "XNAS", AssetClass.ETF, profile),
        ],
        CACHED_FROM,
        cached_to,
        source=YFinanceSource({"XNYS": NYSE}, fetch=fetch),
        clock=NOW,
    )
    assert all(o.error is None for o in outcomes)
    return config


def walk(
    config: TycheConfig,
    first: date = FIRST,
    last: date | None = LAST,
    scheme: FoldScheme = SCHEME,
    **kwargs: Any,
) -> WalkForwardOutcome:
    return run_configured_walk_forward(config, first, last, scheme, clock=NOW, code=CODE, **kwargs)


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> WalkForwardOutcome:
    return walk(workspace(tmp_path_factory.mktemp("walked")))


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    return workspace(tmp_path)


def read(path: Path) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


class TestTheFolds:
    def test_every_fold_runs_its_training_and_test_window(self, walked: WalkForwardOutcome) -> None:
        assert walked.completed
        assert [(str(f.fold.train), str(f.fold.test)) for f in walked.finished] == [
            ("2020-01-02 to 2021-12-31", "2022-01-01 to 2022-12-31"),
            ("2020-01-02 to 2022-12-31", "2023-01-01 to 2023-12-29"),
        ]

    def test_each_window_starts_from_the_starting_cash(self, walked: WalkForwardOutcome) -> None:
        for result in walked.finished:
            assert result.train.strategy.start_equity == 10_000
            assert result.test.strategy.start_equity == 10_000

    def test_the_test_windows_are_joined(self, walked: WalkForwardOutcome) -> None:
        metrics = walked.metrics
        assert metrics is not None
        first, second = walked.finished
        assert metrics.out_of_sample.sessions == first.test.strategy.sessions + (
            second.test.strategy.sessions
        )
        growth = (1 + first.test.strategy.total_return) * (1 + second.test.strategy.total_return)
        assert abs(metrics.out_of_sample.total_return - (growth - 1)) < Decimal("1e-20")


class TestTheRecord:
    def test_is_written_under_reports_in_the_workspace(self, walked: WalkForwardOutcome) -> None:
        folder = walked.record_dir
        assert folder.parent.name == "walk_forward"
        assert folder.name == walked.walk_forward_id
        names = {p.name for p in folder.iterdir()}
        assert {WALK_FORWARD_FILE, "metrics.json", "equity.csv", "folds"} <= names

    def test_says_what_ran_and_how_it_ended(self, walked: WalkForwardOutcome) -> None:
        study = read(walked.record_dir / WALK_FORWARD_FILE)

        assert study["walk_forward_format"] == 1
        assert study["code"]["git_commit"] == CODE.commit
        assert study["config_hash"].startswith("sha256:")
        assert study["range"] == {"first": "2020-01-02", "last": "2023-12-29"}
        assert study["scheme"] == {
            "anchored": True,
            "train_years": 2,
            "test_years": 1,
            "described": "anchored: 2-year first training window, 1-year test windows",
        }
        assert study["train_step"] == "keep the configured parameters"
        assert study["holdout_starts"] == "2024-01-01"
        assert study["strategies"] == [
            {"id": "buy_and_hold", "plugin": "buy_and_hold", "budget": "1.0"}
        ]
        assert study["outcome"] == {
            "completed": True,
            "failure": None,
            "folds_planned": 2,
            "folds_finished": 2,
            "metrics": "metrics.json",
        }

    def test_each_window_has_a_full_backtest_record(self, walked: WalkForwardOutcome) -> None:
        study = read(walked.record_dir / WALK_FORWARD_FILE)
        fold = study["folds"][1]
        assert fold["test"] == {
            "first": "2023-01-01",
            "last": "2023-12-29",
            "run_id": f"{walked.walk_forward_id}-02-test",
            "record": "folds/02-test",
        }
        folder = walked.record_dir / fold["test"]["record"]
        assert {p.name for p in folder.iterdir()} == {
            "run.json",
            "metrics.json",
            "equity.csv",
            "fills.csv",
        }
        run = read(folder / "run.json")
        assert run["run_id"] == fold["test"]["run_id"]
        assert run["part_of"] == {
            "walk_forward": walked.walk_forward_id,
            "fold": 2,
            "window": "test",
            "train_step": "keep the configured parameters",
        }
        assert run["range"]["first_session"] == "2023-01-03"

    def test_metrics_compare_the_joined_test_windows_with_the_benchmark(
        self, walked: WalkForwardOutcome
    ) -> None:
        metrics = read(walked.record_dir / "metrics.json")
        assert walked.metrics is not None

        assert metrics["out_of_sample"]["sessions"] == walked.metrics.out_of_sample.sessions
        assert metrics["benchmark"]["instrument"] == "SPY@ARCX"
        assert metrics["test_windows"] == 2
        assert metrics["test_windows_ahead"] == walked.metrics.tests_ahead
        assert "scaled to start where the previous one ended" in metrics["chaining"]

    def test_equity_has_one_row_per_test_close(self, walked: WalkForwardOutcome) -> None:
        assert walked.metrics is not None
        equity = rows(walked.record_dir / "equity.csv")

        assert len(equity) == walked.metrics.out_of_sample.sessions
        assert [r["fold"] for r in (equity[0], equity[-1])] == ["1", "2"]
        assert equity[0]["equity"] == "10000.00"
        assert equity[0]["benchmark_equity"] == "10000.00"

    def test_two_walk_forwards_in_the_same_second_get_their_own_records(
        self, config: TycheConfig
    ) -> None:
        one = walk(config, date(2022, 1, 3), scheme=FoldScheme(1, 1))
        two = walk(config, date(2022, 1, 3), scheme=FoldScheme(1, 1))

        assert two.walk_forward_id == f"{one.walk_forward_id}-2"


class TestProgress:
    def test_is_told_about_every_window_in_order(self, config: TycheConfig) -> None:
        seen: list[tuple[int, str]] = []

        def progress(fold: Any, kind: Any, outcome: BacktestOutcome, picked: Any) -> None:
            assert picked is None  # no sweep, nothing picked
            seen.append((fold.number, kind.value))

        walk(config, date(2021, 1, 4), scheme=FoldScheme(1, 1), progress=progress)

        assert seen == [(1, "train"), (1, "test"), (2, "train"), (2, "test")]


class TestWhatIsRefused:
    def test_a_range_reaching_the_holdout_is_refused_and_nothing_is_written(
        self, config: TycheConfig
    ) -> None:
        with pytest.raises(HoldoutError):
            walk(config, last=date(2024, 1, 2))

        assert not (config.workspace.reports_dir / "walk_forward").exists()

    def test_a_range_too_short_for_a_test_window_is_refused(self, config: TycheConfig) -> None:
        with pytest.raises(WalkForwardError, match="leaves no test window"):
            walk(config, scheme=FoldScheme(5, 1))

        assert not (config.workspace.reports_dir / "walk_forward").exists()

    def test_missing_history_stops_it_and_the_windows_already_run_stay_recorded(
        self, tmp_path: Path
    ) -> None:
        config = workspace(tmp_path, cached_to=date(2022, 12, 30))

        with pytest.raises(BacktestRequestError, match="tyche data fetch SPY"):
            walk(config, date(2021, 1, 4), last=date(2023, 12, 29), scheme=FoldScheme(1, 1))

        (folder,) = (config.workspace.reports_dir / "walk_forward").iterdir()
        study = read(folder / WALK_FORWARD_FILE)
        assert study["outcome"]["completed"] is False
        assert study["outcome"]["failure"].startswith("stopped: ")
        assert study["outcome"]["folds_finished"] == 1
        assert [f["finished"] for f in study["folds"]] == [True, False]
        assert not (folder / "metrics.json").exists()

    def test_a_window_that_halts_stops_it_and_is_recorded(
        self, config: TycheConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = run_and_record

        def halting_tests(*args: Any, **kwargs: Any) -> BacktestOutcome:
            outcome = original(*args, **kwargs)
            if kwargs["part_of"]["window"] != "test":
                return outcome
            halted = replace(outcome.result.run, completed=False, failure="a stage failed")
            return replace(outcome, result=replace(outcome.result, run=halted))

        monkeypatch.setattr(runtime_walk_forward, "run_and_record", halting_tests)

        outcome = walk(config, date(2022, 1, 3), scheme=FoldScheme(1, 1))

        assert not outcome.completed
        assert outcome.failure == "fold 1's test window halted: a stage failed"
        assert outcome.metrics is None
        study = read(outcome.record_dir / WALK_FORWARD_FILE)
        assert study["outcome"]["failure"] == outcome.failure


class TestTheReport:
    def test_is_written_into_the_record_folder(self, walked: WalkForwardOutcome) -> None:
        path = write_walk_forward_report(walked.record_dir)

        assert path == walked.record_dir / REPORT_FILE
        page = path.read_text(encoding="utf-8")
        assert f"Walk-forward {walked.walk_forward_id}" in page
        for heading in (
            "Out of sample: the test windows joined",
            "Fold by fold: in-sample and out-of-sample",
            "Trading in the test windows",
            "What ran",
            "Data and its limits",
        ):
            assert heading in page
        assert "keep the configured parameters" in page
        assert "not overfitting" in page
        for outside in ("<script", "<link", 'src="http', "url(http", "@import"):
            assert outside not in page

    def test_rebuilding_gives_the_same_file(self, walked: WalkForwardOutcome) -> None:
        first = write_walk_forward_report(walked.record_dir).read_bytes()
        second = write_walk_forward_report(walked.record_dir).read_bytes()

        assert first == second

    def test_shows_each_fold_side_by_side(self, walked: WalkForwardOutcome) -> None:
        record = read_walk_forward(walked.record_dir)
        document = walk_forward_report(record)
        folds = document.sections[1]

        table = folds.blocks[1]
        assert isinstance(table, Table)
        assert [r[1] for r in table.rows] == [
            "2020-01-02 to 2021-12-31",
            "2020-01-02 to 2022-12-30",
        ]
        assert [r[4] for r in table.rows] == [
            "2022-01-03 to 2022-12-30",
            "2023-01-03 to 2023-12-29",
        ]

    def test_a_walk_forward_that_stopped_has_no_report(
        self, config: TycheConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runtime_walk_forward, "measure_walk_forward", _cannot_measure)
        outcome = walk(config, date(2022, 1, 3), scheme=FoldScheme(1, 1))

        with pytest.raises(ReportError, match="did not finish"):
            write_walk_forward_report(outcome.record_dir)

    def test_says_so_when_the_folder_is_not_a_record(self, tmp_path: Path) -> None:
        with pytest.raises(ReportError, match=r"walk_forward\.json is missing"):
            write_walk_forward_report(tmp_path)

    def test_a_record_of_another_format_is_refused(self, walked: WalkForwardOutcome) -> None:
        path = walked.record_dir / WALK_FORWARD_FILE
        original = path.read_text(encoding="utf-8")
        try:
            study = json.loads(original)
            study["walk_forward_format"] = 99
            path.write_text(json.dumps(study), encoding="utf-8")
            with pytest.raises(ReportError, match="format 99"):
                write_walk_forward_report(walked.record_dir)
        finally:
            path.write_text(original, encoding="utf-8")


def _cannot_measure(*args: Any) -> Any:
    raise MetricsError("no closes")

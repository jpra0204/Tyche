"""``tyche sweep``'s wiring, and the walk-forward's train step with a sweep (ADR-0030).

The cache is filled the way `tyche data fetch` fills it, from scripted Yahoo answers,
for SPY and QQQ from October 2019 to the end of 2023: SPY rises and falls in waves,
QQQ climbs slowly. The workspace runs the trend rotation alone, over those two ETFs,
and the sweep ``small`` tries four combinations of it.
"""

import json
import math
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.workspace import add_unbound_profile, keep_candidates
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import YFinanceSource
from tyche.config import (
    ConfigError,
    TycheConfig,
    Workspace,
    init_workspace,
    load_config,
    load_sweep,
)
from tyche.core.backtest import FoldScheme, trial_key
from tyche.core.domain import AssetClass
from tyche.core.sim import SimClock
from tyche.runtime.backtest import BacktestRequestError, CodeVersion, run_configured_backtest
from tyche.runtime.data import CALENDAR_START, fetch_daily_histories, instrument_for
from tyche.runtime.report import REPORT_FILE, ReportError
from tyche.runtime.sweep import (
    PICK_FOLDER,
    SWEEP_FILE,
    SweepOutcome,
    plan_sweep,
    run_configured_sweep,
)
from tyche.runtime.sweep_report import is_sweep, read_sweep, write_sweep_report
from tyche.runtime.trials import TRIALS_FILE, recorded_trial_keys
from tyche.runtime.walk_forward import (
    WALK_FORWARD_FILE,
    WalkForwardOutcome,
    run_configured_walk_forward,
)
from tyche.runtime.walk_forward_report import write_walk_forward_report

NYSE = ExchangeCalendarsCalendar("XNYS", first=CALENDAR_START, last=date(2024, 3, 31))
CACHED_FROM, CACHED_TO = date(2019, 10, 1), date(2023, 12, 29)
FIRST, LAST = date(2021, 1, 4), date(2023, 12, 29)
NOW = SimClock(datetime(2024, 1, 5, 12, 0, tzinfo=UTC))
CODE = CodeVersion("0.0.0", "0123456789abcdef0123", dirty=False)

STRATEGY = """plugin = "trend_rotation"

[parameters]
holdings = 1
momentum_sessions = 20
trend_sessions = 50
instruments = [
    { symbol = "SPY", exchange = "ARCX", asset_class = "etf" },
    { symbol = "QQQ", exchange = "XNAS", asset_class = "etf" },
]
"""

SWEEP = """strategy = "trend_rotation"

[grid]
holdings = [1, 2]
momentum_sessions = [10, 40]
"""


def workspace(root: Path) -> TycheConfig:
    home = root / "home"
    home.mkdir()
    ws = init_workspace(home / "ws", user_home=home)
    keep_candidates(ws.root, "SPY", "QQQ")
    tyche = ws.tyche_config.read_text(encoding="utf-8")
    ws.tyche_config.write_text(
        tyche.replace('buy_and_hold = "1.0"', 'trend_rotation = "1.0"'), encoding="utf-8"
    )
    (ws.strategies_dir / "trend_rotation.toml").write_text(STRATEGY, encoding="utf-8")
    (ws.sweeps_dir / "small.toml").write_text(SWEEP, encoding="utf-8")
    config = load_config(Workspace(ws.root), add_unbound_profile(ws.root))
    profile = config.market_profile
    days = [s.day for s in NYSE.sessions_between(CACHED_FROM, CACHED_TO)]
    spy = [row(d, 300 + i * 0.05 + 25 * math.sin(i / 40)) for i, d in enumerate(days)]
    qqq = [row(d, 350 + i * 0.03) for i, d in enumerate(days)]
    outcomes = fetch_daily_histories(
        config,
        [
            instrument_for("SPY", "ARCX", AssetClass.ETF, profile),
            instrument_for("QQQ", "XNAS", AssetClass.ETF, profile),
        ],
        CACHED_FROM,
        CACHED_TO,
        source=YFinanceSource({"XNYS": NYSE}, fetch=FakeFetch(spy, qqq)),
        clock=NOW,
    )
    assert all(o.error is None for o in outcomes)
    return config


def sweep(config: TycheConfig, first: date = FIRST, last: date = LAST) -> SweepOutcome:
    return run_configured_sweep(
        config, load_sweep(config, "small"), first, last, clock=NOW, code=CODE
    )


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> SweepOutcome:
    return sweep(workspace(tmp_path_factory.mktemp("swept")))


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    return workspace(tmp_path)


def read(path: Path) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


def write_sweep(config: TycheConfig, text: str, name: str = "bad") -> None:
    (config.workspace.sweeps_dir / f"{name}.toml").write_text(text, encoding="utf-8")


class TestReadingASweep:
    def test_reads_the_grid_in_the_order_written(self, config: TycheConfig) -> None:
        spec = load_sweep(config, "small")

        assert spec.strategy_id == "trend_rotation"
        assert spec.grid == {"holdings": (1, 2), "momentum_sessions": (10, 40)}
        assert spec.source == "config/sweeps/small.toml"
        assert spec.sweep_hash.startswith("sha256:")

    def test_the_example_sweep_ships_with_a_new_workspace(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path / "ws", user_home=tmp_path)

        assert (ws.sweeps_dir / "trend_rotation.toml").is_file()

    def test_a_missing_sweep_is_named(self, config: TycheConfig) -> None:
        with pytest.raises(ConfigError, match=r"config/sweeps/nothing\.toml does not exist"):
            load_sweep(config, "nothing")

    def test_the_strategy_needs_a_budget(self, config: TycheConfig) -> None:
        write_sweep(config, 'strategy = "mean_reversion"\n[grid]\nentry_rsi = ["5", "10"]\n')

        with pytest.raises(ConfigError, match="'mean_reversion' has no budget"):
            load_sweep(config, "bad")

    @pytest.mark.parametrize(
        ("grid", "message"),
        [
            ("", "name at least one parameter"),
            ("holdings = []", "grid.holdings: list at least one value"),
            ("holdings = [1, 1]", "grid.holdings: a value is listed more than once"),
        ],
    )
    def test_a_grid_is_checked(self, config: TycheConfig, grid: str, message: str) -> None:
        write_sweep(config, f'strategy = "trend_rotation"\n[grid]\n{grid}\n')

        with pytest.raises(ConfigError, match=message):
            load_sweep(config, "bad")

    @pytest.mark.parametrize(
        ("grid", "message"),
        [
            (
                "holdng = [1, 2]",
                r"config/sweeps/bad.toml: 1 invalid parameter\(s\)\n  parameters.holdng",
            ),
            (
                "holdings = [1, 3]",
                "(?s)config/sweeps/bad.toml: .*holdings: 3 is more than the 2 instruments",
            ),
            ('holdings = ["2"]', "config/sweeps/bad.toml: 1 invalid parameter"),
        ],
    )
    def test_every_combination_is_built_before_anything_runs(
        self, config: TycheConfig, grid: str, message: str
    ) -> None:
        write_sweep(config, f'strategy = "trend_rotation"\n[grid]\n{grid}\n')

        with pytest.raises(ConfigError, match=message):
            plan_sweep(config, load_sweep(config, "bad"))
        assert not (config.workspace.reports_dir / "sweeps").exists()


class TestCountingTheSweepsTrials:
    def test_a_first_sweep_counts_its_own_combinations(self, config: TycheConfig) -> None:
        plan = plan_sweep(config, load_sweep(config, "small"))

        assert (plan.earlier_trials, plan.trials_counted) == (0, 4)
        assert len(set(plan.keys)) == 4

    def test_earlier_backtests_of_the_plugin_count_once(self, config: TycheConfig) -> None:
        run_configured_backtest(config, date(2023, 1, 3), LAST, clock=NOW, code=CODE)

        plan = plan_sweep(config, load_sweep(config, "small"))

        # The configured parameters (momentum 20) are not in the grid: five trials.
        assert (plan.earlier_trials, plan.trials_counted) == (1, 5)

    def test_a_grid_that_repeats_a_recorded_trial_does_not_count_it_twice(
        self, config: TycheConfig
    ) -> None:
        run_configured_backtest(config, date(2023, 1, 3), LAST, clock=NOW, code=CODE)
        write_sweep(
            config, 'strategy = "trend_rotation"\n[grid]\nmomentum_sessions = [20, 40]\n', "again"
        )

        plan = plan_sweep(config, load_sweep(config, "again"))

        assert (plan.earlier_trials, plan.trials_counted) == (1, 2)


class TestTheOrderTrialsRunIn:
    def test_the_combination_needing_most_history_runs_first(self, config: TycheConfig) -> None:
        write_sweep(
            config,
            'strategy = "trend_rotation"\n[grid]\n'
            "holdings = [1, 2]\nmomentum_sessions = [10, 60]\n",
            "order",
        )
        seen: list[int] = []

        outcome = run_configured_sweep(
            config,
            load_sweep(config, "order"),
            date(2023, 1, 3),
            LAST,
            clock=NOW,
            code=CODE,
            progress=lambda plan, trial: seen.append(trial.combination.number),
        )

        # momentum_sessions = 60 needs 61 sessions, more than trend_sessions = 50: trial 2
        # is the first combination with it.
        assert seen == [2, 1, 3, 4]
        assert [t.combination.number for t in outcome.result.trials] == [1, 2, 3, 4]

    def test_missing_history_stops_the_sweep_before_any_other_trial(
        self, config: TycheConfig
    ) -> None:
        write_sweep(
            config, 'strategy = "trend_rotation"\n[grid]\nmomentum_sessions = [10, 400]\n', "long"
        )
        seen: list[int] = []

        with pytest.raises(BacktestRequestError, match="not in the cache yet"):
            run_configured_sweep(
                config,
                load_sweep(config, "long"),
                FIRST,
                LAST,
                clock=NOW,
                code=CODE,
                progress=lambda plan, trial: seen.append(trial.combination.number),
            )

        assert seen == []
        assert not (config.workspace.reports_dir / "sweeps").exists()


class TestASweep:
    def test_runs_every_combination_and_picks_the_highest_sharpe(self, swept: SweepOutcome) -> None:
        result = swept.result
        assert [dict(t.combination.values) for t in result.trials] == [
            {"holdings": 1, "momentum_sessions": 10},
            {"holdings": 1, "momentum_sessions": 40},
            {"holdings": 2, "momentum_sessions": 10},
            {"holdings": 2, "momentum_sessions": 40},
        ]
        assert all(t.metrics is not None for t in result.trials)
        best = result.best
        assert best is not None
        assert best.sharpe == max(t.sharpe for t in result.trials if t.sharpe is not None)

    def test_deflates_the_picks_sharpe_for_every_trial(self, swept: SweepOutcome) -> None:
        deflated = swept.result.deflated

        assert deflated is not None
        assert deflated.trials == 4
        assert 0 < deflated.probability < 1
        assert deflated.moments.count == len(swept.result.best_run.result.closes) - 1  # type: ignore[union-attr]

    def test_writes_the_record_under_reports_in_the_workspace(self, swept: SweepOutcome) -> None:
        folder = swept.record_dir
        assert folder.parent.name == "sweeps"
        assert {p.name for p in folder.iterdir()} == {SWEEP_FILE, TRIALS_FILE, PICK_FOLDER}
        assert {p.name for p in (folder / PICK_FOLDER).iterdir()} == {
            "run.json",
            "metrics.json",
            "equity.csv",
            "fills.csv",
        }

    def test_sweep_json_says_what_ran(self, swept: SweepOutcome) -> None:
        study = read(swept.record_dir / SWEEP_FILE)

        assert study["sweep_format"] == 1
        assert study["sweep_id"] == swept.sweep_id
        assert study["code"]["git_commit"] == CODE.commit
        assert study["range"] == {"first": "2021-01-04", "last": "2023-12-29"}
        assert study["sweep"]["file"] == "config/sweeps/small.toml"
        assert study["sweep"]["content"] == {
            "strategy": "trend_rotation",
            "grid": {"holdings": [1, 2], "momentum_sessions": [10, 40]},
        }
        assert study["outcome"]["trials"] == 4
        assert study["outcome"]["picked"] == swept.result.best.combination.number  # type: ignore[union-attr]
        assert "config/tyche.toml" in study["config"]

    def test_trials_json_holds_every_trial_and_the_pick(self, swept: SweepOutcome) -> None:
        trials = read(swept.record_dir / TRIALS_FILE)
        best = swept.result.best
        assert best is not None

        assert trials["plugin"] == "trend_rotation"
        assert trials["base_parameters"]["momentum_sessions"] == 20
        assert [t["number"] for t in trials["trials"]] == [1, 2, 3, 4]
        first = trials["trials"][0]
        full = {**trials["base_parameters"], "holdings": 1, "momentum_sessions": 10}
        assert first["key"] == trial_key("trend_rotation", "1", full)
        assert first["parameters"] == {"holdings": 1, "momentum_sessions": 10}
        assert {"sharpe", "session_sharpe", "cagr", "max_drawdown", "closed_trades"} <= set(first)
        assert trials["pick"] == {
            "number": best.combination.number,
            "parameters": dict(best.combination.values),
            "record": PICK_FOLDER,
        }
        assert trials["trials_counted"] == {"total": 4, "this_grid": 4, "recorded_before": 0}
        deflated = trials["deflated_sharpe"]
        assert deflated["trials"] == 4
        assert re.fullmatch(r"[01]\.\d{6}", deflated["probability"])
        assert isinstance(trials["warnings"], list)

    def test_the_picks_record_states_its_parameters(self, swept: SweepOutcome) -> None:
        run = read(swept.record_dir / PICK_FOLDER / "run.json")
        best = swept.result.best
        assert best is not None

        assert run["part_of"] == {"sweep": swept.sweep_id, "trial": best.combination.number}
        (strategy,) = run["strategies"]
        assert strategy["parameters"]["holdings"] == best.combination.values["holdings"]
        assert strategy["parameters"]["trend_sessions"] == 50

    def test_its_trials_are_counted_by_the_next_sweep(self, swept: SweepOutcome) -> None:
        reports = swept.record_dir.parent.parent
        keys = recorded_trial_keys(reports, "trend_rotation")

        assert keys == {t["key"] for t in read(swept.record_dir / TRIALS_FILE)["trials"]}


class TestTheSweepReport:
    def test_is_built_from_the_record(self, swept: SweepOutcome) -> None:
        assert is_sweep(swept.record_dir)

        path = write_sweep_report(swept.record_dir)

        assert path == swept.record_dir / REPORT_FILE
        html = path.read_text(encoding="utf-8")
        assert "Sweep " + swept.sweep_id in html
        assert "How much to trust the pick" in html
        assert "Every figure here is in-sample" in html
        assert "Trials counted: 4." in html
        assert "Every trial" in html

    def test_records_and_warns_of_trials_the_drawdown_kill_halted(
        self, swept: SweepOutcome, tmp_path: Path
    ) -> None:
        trials = read(swept.record_dir / TRIALS_FILE)
        assert all(t["halted_at"] is None for t in trials["trials"])
        assert "The drawdown kill halted" not in write_sweep_report(swept.record_dir).read_text()

        copy = tmp_path / "sweep"
        shutil.copytree(swept.record_dir, copy)
        trials["trials"][1]["halted_at"] = "2021-03-04T21:00:00+00:00"
        (copy / TRIALS_FILE).write_text(json.dumps(trials))

        html = write_sweep_report(copy).read_text(encoding="utf-8")
        assert "The drawdown kill halted 1 of 4 trials: trial 2 (2021-03-04)." in html

    def test_reads_the_picks_full_record(self, swept: SweepOutcome) -> None:
        record = read_sweep(swept.record_dir)

        assert len(record.pick.equity) == len(swept.result.best_run.result.closes)  # type: ignore[union-attr]

    def test_a_folder_without_a_sweep_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ReportError, match=r"sweep\.json is missing"):
            read_sweep(tmp_path)


SCHEME = FoldScheme(train_years=1, test_years=1)


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> WalkForwardOutcome:
    config = workspace(tmp_path_factory.mktemp("walked"))
    return run_configured_walk_forward(
        config,
        date(2021, 1, 4),
        LAST,
        SCHEME,
        clock=NOW,
        code=CODE,
        sweep=load_sweep(config, "small"),
    )


class TestAWalkForwardWithASweep:
    def test_each_training_window_picks_what_its_test_window_runs(
        self, walked: WalkForwardOutcome
    ) -> None:
        assert walked.completed
        assert walked.picks is not None
        assert sorted(walked.picks) == [1, 2]
        for result in walked.finished:
            swept = walked.picks[result.fold.number]
            assert swept.best is not None
            assert (swept.first, swept.last) == (result.fold.train.first, result.fold.train.last)
            assert result.train.strategy.sharpe == swept.best.sharpe
            folder = walked.record_dir / f"folds/{result.fold.number:02d}-test"
            (strategy,) = read(folder / "run.json")["strategies"]
            assert strategy["parameters"]["holdings"] == swept.best.combination.values["holdings"]

    def test_the_training_window_keeps_the_pick_and_every_trial(
        self, walked: WalkForwardOutcome
    ) -> None:
        folder = walked.record_dir / "folds/01-train"

        assert {p.name for p in folder.iterdir()} == {
            "run.json",
            "metrics.json",
            "equity.csv",
            "fills.csv",
            TRIALS_FILE,
        }
        trials = read(folder / TRIALS_FILE)
        assert len(trials["trials"]) == 4
        assert trials["pick"]["record"] == "."
        assert read(folder / "run.json")["part_of"]["trial"] == trials["pick"]["number"]

    def test_the_record_names_the_sweep_and_each_pick(self, walked: WalkForwardOutcome) -> None:
        study = read(walked.record_dir / WALK_FORWARD_FILE)

        assert study["train_step"] == (
            "pick the highest Sharpe ratio of sweep 'small' (4 combinations of "
            "trend_rotation) on the training window"
        )
        assert study["sweep"]["trials_counted"] == {
            "total": 4,
            "this_grid": 4,
            "recorded_before": 0,
        }
        fold = study["folds"][0]
        assert fold["train"]["trials"] == "folds/01-train/trials.json"
        assert fold["picked"]["parameters"] == dict(walked.picks[1].best.combination.values)  # type: ignore[index, union-attr]

    def test_each_combination_counts_once_however_many_folds_ran_it(
        self, walked: WalkForwardOutcome
    ) -> None:
        reports = walked.record_dir.parent.parent

        assert len(recorded_trial_keys(reports, "trend_rotation")) == 4

    def test_the_report_shows_each_pick(self, walked: WalkForwardOutcome) -> None:
        html = write_walk_forward_report(walked.record_dir).read_text(encoding="utf-8")

        assert "What each training window picked" in html
        assert "The train step picked parameters on each training window" in html
        assert "Trials counted for trend_rotation: 4" in html

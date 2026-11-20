"""``tyche backtest``'s wiring: a workspace and its cache in, a run record out.

The cache is filled the way `tyche data fetch` fills it, from scripted Yahoo answers,
for SPY and QQQ from October to December 2023, just before the template's holdout.
"""

import csv
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.workspace import keep_candidates
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import YFinanceSource
from tyche.config import TycheConfig, Workspace, init_workspace, load_config
from tyche.core.backtest import BacktestMetrics, BacktestResult, HoldoutError, MetricsError
from tyche.core.domain import AssetClass, Currency
from tyche.core.sim import SimClock
from tyche.runtime import backtest as runtime_backtest
from tyche.runtime.backtest import (
    BacktestOutcome,
    BacktestRequestError,
    CodeVersion,
    current_code_version,
    run_configured_backtest,
)
from tyche.runtime.data import CALENDAR_START, fetch_daily_histories, instrument_for

NYSE = ExchangeCalendarsCalendar("XNYS", first=CALENDAR_START, last=date(2024, 3, 31))
CACHED_FROM, CACHED_TO = date(2023, 10, 2), date(2023, 12, 29)
FIRST, LAST = date(2023, 11, 1), date(2023, 12, 29)
NOW = SimClock(datetime(2024, 1, 5, 12, 0, tzinfo=UTC))
CODE = CodeVersion("0.0.0", "0123456789abcdef0123", dirty=False)


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    home = tmp_path / "home"
    home.mkdir()
    keep_candidates(init_workspace(home / "ws", user_home=home).root, "SPY", "QQQ")
    config = load_config(Workspace(home / "ws"))
    profile = config.market_profile
    days = [s.day for s in NYSE.sessions_between(CACHED_FROM, CACHED_TO)]
    fetch = FakeFetch([row(d, 400 + i) for i, d in enumerate(days)], [row(d, 350) for d in days])
    outcomes = fetch_daily_histories(
        config,
        [
            instrument_for("SPY", "ARCX", AssetClass.ETF, profile),
            instrument_for("QQQ", "XNAS", AssetClass.ETF, profile),
        ],
        CACHED_FROM,
        CACHED_TO,
        source=YFinanceSource({"XNYS": NYSE}, fetch=fetch),
        clock=NOW,
    )
    assert all(o.error is None for o in outcomes)
    return config


def backtest(config: TycheConfig, first: date = FIRST, last: date | None = LAST) -> BacktestOutcome:
    return run_configured_backtest(config, first, last, clock=NOW, code=CODE)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


class TestTheRunRecord:
    def test_is_written_under_reports_in_the_workspace(self, config: TycheConfig) -> None:
        outcome = backtest(config)

        assert outcome.result.run.completed
        assert outcome.record_dir == config.workspace.reports_dir / "backtests" / outcome.run_id
        assert outcome.run_id == "20240105T120000Z-" + config.config_hash[7:15]
        assert sorted(p.name for p in outcome.record_dir.iterdir()) == [
            "equity.csv",
            "fills.csv",
            "metrics.json",
            "run.json",
        ]

    def test_says_which_code_and_config_ran(self, config: TycheConfig) -> None:
        record = json.loads((backtest(config).record_dir / "run.json").read_text())

        assert record["record_format"] == 1
        assert record["mode"] == "backtest"
        assert record["code"]["tyche_version"] == "0.0.0"
        assert record["code"]["git_commit"] == CODE.commit
        assert record["code"]["git_dirty"] is False
        assert record["config_hash"] == config.config_hash
        assert record["config"] == json.loads(json.dumps(config.snapshot))
        assert "config/tyche.toml" in record["config"]

    def test_states_the_range_warm_up_holdout_and_execution_rules(
        self, config: TycheConfig
    ) -> None:
        record = json.loads((backtest(config).record_dir / "run.json").read_text())

        assert record["range"]["first"] == "2023-11-01"
        assert record["range"]["last_session"] == "2023-12-29"
        assert record["range"]["sessions"] == len(NYSE.sessions_between(FIRST, LAST))
        assert record["warm_up"] == {"sessions_needed": 20, "sessions": 20, "first": "2023-10-04"}
        assert record["holdout_starts"] == "2024-01-01"
        assert record["starting_cash"] == {"amount": "10000", "currency": "USD"}
        assert record["execution"] == {"rebalance_band": "0.10", "price_buffer": "0.02"}
        assert record["strategies"] == [
            {"id": "buy_and_hold", "plugin": "buy_and_hold", "version": "1", "budget": "1.0"}
        ]

    def test_lists_the_data_used(self, config: TycheConfig) -> None:
        record = json.loads((backtest(config).record_dir / "run.json").read_text())

        spy, qqq = record["data"]
        assert (spy["instrument"], qqq["instrument"]) == ("SPY@ARCX", "QQQ@XNAS")
        assert spy["source"] == "yfinance"
        assert spy["bars"] == 20 + len(NYSE.sessions_between(FIRST, LAST))
        assert spy["fetched_from"] == NOW.now().isoformat()

    def test_states_the_outcome(self, config: TycheConfig) -> None:
        record = json.loads((backtest(config).record_dir / "run.json").read_text())

        outcome = record["outcome"]
        assert outcome["completed"] is True
        assert outcome["failure"] is None
        assert outcome["fills"] == 1
        assert outcome["free_riding"] == 0
        assert outcome["agrees_with_broker"] is True
        assert outcome["final_equity"]["currency"] == "USD"
        assert (outcome["metrics"], outcome["metrics_error"]) == ("metrics.json", None)

    def test_names_the_benchmark_and_the_data_it_used(self, config: TycheConfig) -> None:
        record = json.loads((backtest(config).record_dir / "run.json").read_text())

        benchmark = record["benchmark"]
        assert benchmark["instrument"] == "SPY@ARCX"
        assert benchmark["method"].startswith("total return")
        assert benchmark["data"] == record["data"][0]

    def test_equity_has_one_row_per_session_close(self, config: TycheConfig) -> None:
        outcome = backtest(config)

        equity = rows(outcome.record_dir / "equity.csv")
        assert len(equity) == len(NYSE.sessions_between(FIRST, LAST))
        assert equity[0]["equity"] == "10000"
        assert equity[0]["benchmark_equity"] == "10000.00"
        assert equity[0]["currency"] == "USD"
        last = outcome.result.account.equity(outcome.result.account.currencies[0])
        assert equity[-1]["equity"] == str(last.amount)

    def test_fills_lists_each_fill_with_its_costs(self, config: TycheConfig) -> None:
        [fill] = rows(backtest(config).record_dir / "fills.csv")

        assert (fill["instrument"], fill["side"], fill["trade_date"]) == (
            "SPY@ARCX",
            "buy",
            "2023-11-02",
        )
        assert float(fill["commission"]) >= 1.0  # at least the minimum commission

    def test_metrics_compare_the_run_with_the_benchmark(self, config: TycheConfig) -> None:
        outcome = backtest(config)
        metrics = json.loads((outcome.record_dir / "metrics.json").read_text())

        assert metrics["metrics_format"] == 1
        assert metrics["run_id"] == outcome.run_id
        assert metrics["conventions"] == {
            "sessions_per_year": 252,
            "days_per_year": "365.25",
            "risk_free_rate": "0",
        }
        strategy, benchmark = metrics["strategy"], metrics["benchmark"]
        assert benchmark["instrument"] == "SPY@ARCX"
        assert strategy["start_equity"] == benchmark["start_equity"] == "10000.00"
        assert strategy["sessions"] == benchmark["sessions"]
        # SPY closes at 400 plus one a session from the first cached day, pays nothing,
        # and the benchmark holds it from the first close to the last.
        days = [s.day for s in NYSE.sessions_between(CACHED_FROM, CACHED_TO)]
        first_close, last_close = 400 + days.index(FIRST), 400 + days.index(LAST)
        expected = Decimal(10000) * last_close / first_close
        assert benchmark["end_equity"] == str(expected.quantize(Decimal("0.01")))
        assert benchmark["exposure"] == "1.000000"
        assert Decimal(strategy["exposure"]) < 1
        versus = Decimal(strategy["total_return"]) - Decimal(benchmark["total_return"])
        assert abs(Decimal(metrics["versus_benchmark"]["total_return"]) - versus) <= Decimal(
            "0.000001"
        )
        assert metrics["trading"]["closed_trades"] == 0
        assert metrics["trading"]["win_rate"] is None
        assert metrics["trading"]["still_open"] == 1
        assert Decimal(metrics["trading"]["costs"]) >= 1

    def test_a_run_that_cannot_be_measured_is_still_recorded(
        self, config: TycheConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def cannot_measure(result: BacktestResult, currency: Currency) -> BacktestMetrics:
            raise MetricsError("no equity to measure")

        monkeypatch.setattr(runtime_backtest, "measure_backtest", cannot_measure)

        outcome = backtest(config)

        assert (outcome.metrics, outcome.metrics_error) == (None, "no equity to measure")
        record = json.loads((outcome.record_dir / "run.json").read_text())
        assert record["outcome"]["metrics"] is None
        assert record["outcome"]["metrics_error"] == "no equity to measure"
        assert not (outcome.record_dir / "metrics.json").exists()
        assert {row["benchmark_equity"] for row in rows(outcome.record_dir / "equity.csv")} == {""}

    def test_two_runs_in_the_same_second_get_their_own_records(self, config: TycheConfig) -> None:
        first, second = backtest(config), backtest(config)

        assert second.run_id == first.run_id + "-2"
        assert (second.record_dir / "run.json").is_file()


class TestTheRange:
    def test_ends_the_day_before_the_holdout_by_default(self, config: TycheConfig) -> None:
        outcome = backtest(config, last=None)

        assert outcome.last == date(2023, 12, 31)
        assert outcome.result.run.completed

    def test_a_range_reaching_the_holdout_is_refused_and_nothing_is_written(
        self, config: TycheConfig
    ) -> None:
        with pytest.raises(HoldoutError, match="2024-01-01 on is the reserved holdout"):
            backtest(config, last=date(2024, 1, 2))

        assert not config.workspace.reports_dir.exists()

    def test_history_not_in_the_cache_is_named_with_the_command_to_fetch_it(
        self, config: TycheConfig
    ) -> None:
        with pytest.raises(BacktestRequestError) as caught:
            backtest(config, first=date(2023, 6, 1))

        message = str(caught.value)
        assert (
            "SPY@ARCX: sessions from 2023-05-03 to 2023-09-29 are not in the cache yet" in message
        )
        assert "tyche data fetch SPY --exchange ARCX --from 2023-05-03 --to 2023-09-29" in message

    def test_cannot_start_before_the_calendars_do(self, config: TycheConfig) -> None:
        with pytest.raises(BacktestRequestError, match="earliest date Tyche can backtest from"):
            backtest(config, first=date(1989, 12, 29))

    def test_an_empty_range_is_refused(self, config: TycheConfig) -> None:
        with pytest.raises(BacktestRequestError, match="empty date range"):
            backtest(config, first=LAST, last=FIRST)


class FakeGit:
    def __init__(self, answers: dict[str, str | None]) -> None:
        self.answers = answers

    def __call__(self, arguments: Sequence[str]) -> str | None:
        return self.answers.get(arguments[0])


class TestCodeVersion:
    HEAD = "0123456789abcdef0123456789abcdef01234567\n"

    def test_a_clean_checkout(self) -> None:
        code = current_code_version(FakeGit({"rev-parse": self.HEAD, "status": "", "ls-files": ""}))

        assert code.commit == self.HEAD.strip()
        assert not code.dirty
        assert str(code) == f"{code.tyche}+g0123456789ab"

    def test_changed_tracked_files_make_it_dirty(self) -> None:
        git = FakeGit(
            {"rev-parse": self.HEAD, "status": " M src/tyche/cli/__init__.py\n", "ls-files": ""}
        )

        code = current_code_version(git)

        assert code.dirty
        assert str(code).endswith("+g0123456789ab.dirty")

    def test_new_source_files_make_it_dirty(self) -> None:
        git = FakeGit({"rev-parse": self.HEAD, "status": "", "ls-files": "src/tyche/new.py\n"})

        assert current_code_version(git).dirty

    def test_outside_a_git_checkout_only_the_version_is_known(self) -> None:
        code = current_code_version(FakeGit({}))

        assert (code.commit, code.dirty) == (None, False)
        assert str(code) == code.tyche

    def test_this_checkout_has_a_commit(self) -> None:
        assert current_code_version().commit is not None

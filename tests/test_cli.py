"""The `tyche` command, run as a user would: version, init, config, data, backtest,
walk-forward, report, kill and resume."""

import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

import tyche
from tests.adapters.data.test_yfinance_source import row
from tests.runtime.test_kill_switch import save
from tests.support import checkpoints
from tests.support.market import JANUARY_2024
from tests.support.reconciliation import unreconciled
from tests.support.workspace import BACKTEST, keep_candidates
from tyche import cli
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data.yfinance_source import UnknownSymbolError, YahooRow
from tyche.adapters.kill_switch import FlagFileKillSwitch
from tyche.cli import app
from tyche.config.workspace import Workspace
from tyche.core.domain import Reconciliation
from tyche.core.ports import Alert, AlertKind, NotifierError
from tyche.runtime import data as runtime_data
from tyche.runtime.backtest import BacktestOutcome, run_configured_backtest
from tyche.runtime.paper import PaperOutcome
from tyche.runtime.report import ReportError
from tyche.runtime.walk_forward import WalkForwardOutcome, run_configured_walk_forward

runner = CliRunner()

# Rich colours help text when it detects a CI service or FORCE_COLOR, even without a
# terminal. Tests compare words, not styling.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake home directory, with TYCHE_HOME unset, so no test touches the real one."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.delenv("TYCHE_HOME", raising=False)
    return fake


def test_version_matches_package_metadata() -> None:
    assert tyche.__version__ == version("tyche")


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"tyche {tyche.__version__}"


def test_no_arguments_prints_help() -> None:
    result = runner.invoke(app, [])
    output = plain(result.output)

    assert "Usage: tyche" in output
    assert "init" in output


def test_module_is_runnable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tyche", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"tyche {tyche.__version__}"


class TestInit:
    def test_creates_the_default_workspace(self, home: Path) -> None:
        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (home / "tyche-workspace" / "config" / "tyche.toml").is_file()
        assert "git init" in result.stdout
        assert "export TYCHE_HOME" not in result.stdout  # the default needs no export

    def test_a_custom_location_says_how_to_point_tyche_at_it(self, home: Path) -> None:
        target = home / "elsewhere"

        result = runner.invoke(app, ["init", "--home", str(target)])

        assert result.exit_code == 0, result.output
        assert f"export TYCHE_HOME={target.resolve()}" in result.stdout
        export_line = result.stdout.index("export TYCHE_HOME")
        assert export_line < result.stdout.index("tyche config check")

    def test_uses_the_environment_variable(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TYCHE_HOME", str(home / "from-env"))

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (home / "from-env" / ".env").is_file()

    def test_refuses_an_unsafe_location(self, home: Path) -> None:
        result = runner.invoke(app, ["init", "--home", str(home / "Documents" / "ws")])

        assert result.exit_code == 1
        assert "Error:" in result.stderr
        assert "inside ~/Documents" in result.stderr
        assert not (home / "Documents").exists()

    def test_never_overwrites(self, home: Path) -> None:
        assert runner.invoke(app, ["init"]).exit_code == 0

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 1
        assert "is not empty" in result.stderr


class TestConfigCheck:
    def test_reports_a_valid_configuration(self, home: Path) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 0, result.output
        assert "Configuration is valid" in result.stdout
        assert "Market profile: US" in result.stdout
        assert "Costs checked:  2026-11-17" in result.stdout
        assert "Execution:      rebalance band 0.10, price buffer 0.02" in result.stdout
        assert "buy_and_hold (buy_and_hold), budget 1.0" in result.stdout
        assert "cash:" not in result.stdout
        assert "Config hash:    sha256:" in result.stdout

    def test_reports_the_risk_profile_and_the_guardrails(self, home: Path) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 0, result.output
        assert (
            "Risk profile:   default: risk per trade 0.01, 5 positions, position size 0.20, "
            "daily loss 0.03, drawdown kill 0.15"
        ) in result.stdout
        assert "Guardrails:     long only, no leverage; capital 700 USD, order 350 USD" in (
            result.stdout
        )
        assert "the money caps in paper and live" in result.stdout
        assert "the daily loss limit and the drawdown kill in every run" in result.stdout

    def test_checks_against_the_chosen_risk_profile(self, home: Path) -> None:
        runner.invoke(app, ["init"])
        risk_dir = home / "tyche-workspace" / "config" / "risk"
        strict = (
            (risk_dir / "default.toml")
            .read_text()
            .replace('max_position_size = "0.20"', 'max_position_size = "0.05"')
        )
        (risk_dir / "safecash.toml").write_text(strict)
        strategy_file = home / "tyche-workspace" / "config" / "strategies" / "buy_and_hold.toml"
        with strategy_file.open("a") as file:
            file.write('\n[risk]\nmax_position_size = "0.10"\n')

        default = runner.invoke(app, ["config", "check"])
        safecash = runner.invoke(app, ["config", "check", "--risk-profile", "safecash"])

        assert default.exit_code == 0, default.output
        assert "also within the guardrails: safecash" in default.stdout
        assert "own limits: position size 0.10" in default.stdout
        assert safecash.exit_code == 1
        assert "risk.max_position_size = 0.10 is above max_position_size = 0.05" in (
            safecash.stderr
        )

    def test_an_unknown_risk_profile_fails_with_the_ones_available(self, home: Path) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config", "check", "--risk-profile", "riskybusiness"])

        assert result.exit_code == 1
        assert "no risk profile named 'riskybusiness'" in result.stderr
        assert "available: default" in result.stderr

    def test_lists_the_cash_left_after_budgets(self, home: Path) -> None:
        runner.invoke(app, ["init"])
        config_file = home / "tyche-workspace" / "config" / "tyche.toml"
        config_file.write_text(
            'schema_version = 1\nmarket_profile = "US"\n'
            + BACKTEST
            + '[strategies]\nbuy_and_hold = "0.8"\n'
        )

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 0, result.output
        assert "budget 0.8" in result.stdout
        assert "cash: 0.2" in result.stdout

    def test_invalid_strategy_parameters_fail_with_the_file_and_key(self, home: Path) -> None:
        runner.invoke(app, ["init"])
        strategy_file = home / "tyche-workspace" / "config" / "strategies" / "buy_and_hold.toml"
        strategy_file.write_text('plugin = "buy_and_hold"\n[parameters]\nsymbol = "SPY"\n')

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 1
        assert "config/strategies/buy_and_hold.toml: 2 invalid parameter(s)" in result.stderr
        assert "parameters.exchange: Field required" in result.stderr

    def test_an_invalid_configuration_fails_with_the_file_and_key(self, home: Path) -> None:
        runner.invoke(app, ["init"])
        config_file = home / "tyche-workspace" / "config" / "tyche.toml"
        config_file.write_text('schema_version = 1\nmarket_profile = "US"\ntypo = 1\n')

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 1
        assert "config/tyche.toml" in result.stderr
        assert "typo: Extra inputs are not permitted" in result.stderr

    def test_a_missing_workspace_fails(self, home: Path) -> None:
        result = runner.invoke(app, ["config", "check", "--home", str(home / "nowhere")])

        assert result.exit_code == 1
        assert "config/tyche.toml is missing" in result.stderr

    def test_an_empty_tyche_home_fails(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYCHE_HOME", "")

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 1
        assert "TYCHE_HOME is set but empty" in result.stderr


class TestDataFetch:
    @pytest.fixture
    def offline(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, date, date]]:
        """Replace Yahoo with canned rows for January 2024; record every request."""
        calls: list[tuple[str, date, date]] = []

        def fake_fetcher(
            cache_dir: Path | None = None,
        ) -> Callable[[str, date, date], list[YahooRow]]:
            def fetch(ticker: str, start: date, end: date) -> list[YahooRow]:
                calls.append((ticker, start, end))
                if ticker == "ZZZQX":
                    raise UnknownSymbolError("no timezone found")
                rows = [row(day) for day in JANUARY_2024 if start <= day < end]
                if rows:
                    rows[2] = row(rows[2].day, dividend=0.5)
                return rows

            return fetch

        monkeypatch.setattr(runtime_data, "yfinance_fetcher", fake_fetcher)
        return calls

    def test_fetches_and_summarises(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app,
            [
                "data",
                "fetch",
                "SPY",
                "--exchange",
                "ARCX",
                "--from",
                "2024-01-02",
                "--to",
                "2024-01-16",
            ],
        )

        assert result.exit_code == 0, result.output
        assert (
            "SPY@ARCX: 10 bars, 2024-01-02 to 2024-01-16; 1 distribution; 0 splits" in result.stdout
        )
        assert offline == [("SPY", date(2024, 1, 2), date(2024, 1, 17))]

    def test_lists_data_issues(self, home: Path, offline: list[tuple[str, date, date]]) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app,
            [
                "data",
                "fetch",
                "SPY",
                "--exchange",
                "ARCX",
                "--from",
                "2024-01-02",
                "--to",
                "2024-01-31",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "data issue(s):" in result.stdout
        assert "2024-01-17 missing_session: no bar for this session" in result.stdout
        assert "... and" in result.stdout  # more than ten missing sessions after 16 January

    def test_a_failed_symbol_is_reported_and_fails_the_command(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app,
            [
                "data",
                "fetch",
                "ZZZQX",
                "SPY",
                "--exchange",
                "XNAS",
                "--from",
                "2024-01-02",
                "--to",
                "2024-01-16",
            ],
        )

        assert result.exit_code == 1
        assert "Error: ZZZQX@XNAS: Yahoo Finance does not know the symbol 'ZZZQX'" in result.stderr
        assert "SPY@XNAS: 10 bars" in result.stdout

    def test_all_fetches_every_candidate_and_the_benchmark_once(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app, ["data", "fetch", "--all", "--from", "2024-01-02", "--to", "2024-01-16"]
        )

        assert result.exit_code == 0, result.output
        # The template's nine candidates; its benchmark, SPY, is one of them.
        assert [ticker for ticker, _, _ in offline] == [
            "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "VNQ"
        ]  # fmt: skip
        assert "VNQ@ARCX: 10 bars" in result.stdout

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["--all", "SPY"], "give no symbols, --exchange or --asset-class with it"),
            (["--all", "--exchange", "ARCX"], "give no symbols, --exchange or --asset-class"),
            (["--all", "--asset-class", "stock"], "give no symbols, --exchange or --asset-class"),
            ([], "name the symbols to fetch, or give --all"),
            (["SPY"], "--exchange is needed with symbols"),
        ],
    )
    def test_symbols_or_all_but_not_both(
        self,
        home: Path,
        offline: list[tuple[str, date, date]],
        arguments: list[str],
        message: str,
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["data", "fetch", *arguments])

        assert result.exit_code == 1
        assert message in plain(result.stderr)
        assert offline == []

    def test_an_unknown_exchange_fails_before_fetching(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["data", "fetch", "XIU", "--exchange", "XTSE"])

        assert result.exit_code == 1
        assert "unknown exchange 'XTSE'" in result.stderr
        assert offline == []

    def test_needs_a_workspace(self, home: Path, offline: list[tuple[str, date, date]]) -> None:
        result = runner.invoke(app, ["data", "fetch", "SPY", "--exchange", "ARCX"])

        assert result.exit_code == 1
        assert "config/tyche.toml is missing" in result.stderr

    def test_a_range_with_no_sessions_says_so(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app,
            [
                "data",
                "fetch",
                "SPY",
                "--exchange",
                "ARCX",
                "--from",
                "2024-01-13",
                "--to",
                "2024-01-15",
            ],
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == "SPY@ARCX: no bars in this range"

    def test_a_short_issue_list_is_shown_in_full(
        self, home: Path, offline: list[tuple[str, date, date]]
    ) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(
            app,
            [
                "data",
                "fetch",
                "SPY",
                "--exchange",
                "ARCX",
                "--from",
                "2024-01-02",
                "--to",
                "2024-01-17",
            ],
        )

        assert "1 data issue(s):" in result.stdout
        assert "2024-01-17 missing_session" in result.stdout
        assert "... and" not in result.stdout


class TestBacktest:
    @pytest.fixture
    def fetched(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A workspace whose cache holds SPY and QQQ for October to December 2023."""
        nyse = ExchangeCalendarsCalendar("XNYS", first=date(2023, 1, 1), last=date(2024, 1, 31))

        def fake_fetcher(
            cache_dir: Path | None = None,
        ) -> Callable[[str, date, date], list[YahooRow]]:
            def fetch(ticker: str, start: date, end: date) -> list[YahooRow]:
                days = [s.day for s in nyse.sessions_between(start, end) if s.day < end]
                if ticker == "QQQ":  # Yahoo misses one QQQ session
                    days.remove(date(2023, 11, 15))
                return [row(day, 400.0 + i) for i, day in enumerate(days)]

            return fetch

        monkeypatch.setattr(runtime_data, "yfinance_fetcher", fake_fetcher)
        assert runner.invoke(app, ["init"]).exit_code == 0
        keep_candidates(home / "tyche-workspace", "SPY", "QQQ")
        for symbol, exchange in (("SPY", "ARCX"), ("QQQ", "XNAS")):
            arguments = ["data", "fetch", symbol, "--exchange", exchange]
            result = runner.invoke(app, [*arguments, "--from", "2023-10-02", "--to", "2023-12-29"])
            assert result.exit_code == 0, result.output
        return home / "tyche-workspace"

    def test_runs_records_and_summarises(self, fetched: Path) -> None:
        result = runner.invoke(app, ["backtest", "--from", "2023-11-01"])

        assert result.exit_code == 0, result.output
        out = result.stdout
        assert re.search(r"^Backtest \d{8}T\d{6}Z-[0-9a-f]{8}: completed$", out, re.MULTILINE)
        assert "Range:         2023-11-01 to 2023-12-31, 41 sessions" in out
        assert "Warm-up:       20 sessions from 2023-10-04 (20 needed)" in out
        assert "Starting cash: 10000 USD" in out
        assert "Fills:         1; free-riding violations: 0" in out
        assert (
            "Risk profile:  default; the risk gate shrank 41 contributions and blocked 0 entries"
        ) in out
        assert "Account rules: daily loss limit hit after 0 sessions; drawdown kill never hit" in (
            out
        )
        assert "Data issues:   1, listed by `tyche data fetch`" in out
        assert re.search(r"^  Metrics\s+strategy\s+SPY@ARCX total return$", out, re.MULTILINE)
        for figure in ("CAGR", "Volatility", "Sharpe (rf 0)", "Sortino (rf 0)", "Max drawdown"):
            assert re.search(rf"^    {re.escape(figure)}\s+\S+\s+\S+$", out, re.MULTILINE)
        assert re.search(r"^    Exposure\s+\d+\.\d\d%\s+100\.00%$", out, re.MULTILINE)
        assert "Trades:        0 closed, win rate n/a; 1 still open" in out
        record = re.search(r"Record:\s+(\S+)", out)
        assert record is not None
        assert Path(record.group(1)).is_file()
        assert Path(record.group(1)).is_relative_to(fetched / "reports" / "backtests")
        report = re.search(r"Report:\s+(\S+)", out)
        assert report is not None
        assert Path(report.group(1)) == Path(record.group(1)).parent / "report.html"
        assert Path(report.group(1)).is_file()

    def test_compares_risk_profiles_side_by_side(self, fetched: Path) -> None:
        risk = fetched / "config" / "risk"
        wide = (risk / "default.toml").read_text().replace('"0.20"', '"0.25"')
        (risk / "wide.toml").write_text(wide)

        result = runner.invoke(app, ["compare-profiles", "--from", "2023-11-01"])

        assert result.exit_code == 0, result.output
        out = result.stdout
        assert "Comparing 2 risk profiles: default, wide" in out
        assert re.search(r"^  default: CAGR .*; drawdown kill never hit$", out, re.MULTILINE)
        assert re.search(r"^  wide: CAGR ", out, re.MULTILINE)
        assert "the report names no best one" in out
        report = re.search(r"Report:\s+(\S+)", out)
        assert report is not None
        assert Path(report.group(1)).is_relative_to(fetched / "reports" / "profiles")
        comparison = Path(report.group(1)).parent.name
        rebuilt = runner.invoke(app, ["report", comparison])
        assert rebuilt.exit_code == 0, rebuilt.output

    def test_compare_profiles_needs_two(self, fetched: Path) -> None:
        result = runner.invoke(app, ["compare-profiles", "--from", "2023-11-01"])

        assert result.exit_code == 1
        assert "at least two risk profiles" in plain(result.stderr)

    def test_runs_under_a_chosen_risk_profile(self, fetched: Path) -> None:
        risk = fetched / "config" / "risk"
        wide = (risk / "default.toml").read_text().replace('"0.20"', '"0.25"')
        (risk / "wide.toml").write_text(wide)

        result = runner.invoke(app, ["backtest", "--from", "2023-11-01", "--risk-profile", "wide"])

        assert result.exit_code == 0, result.output
        assert "Risk profile:  wide;" in result.stdout
        record = re.search(r"Record:\s+(\S+)", result.stdout)
        assert record is not None
        assert json.loads(Path(record.group(1)).read_text())["risk"]["max_position_size"] == "0.25"

    @pytest.mark.parametrize("command", ["backtest", "walk-forward", "sweep", "capital"])
    def test_an_unknown_risk_profile_is_refused(self, fetched: Path, command: str) -> None:
        arguments = [command, *(["trend_rotation"] if command == "sweep" else [])]
        result = runner.invoke(app, [*arguments, "--from", "2023-11-01", "--risk-profile", "nope"])

        assert result.exit_code == 1
        assert "no risk profile named 'nope'" in result.output

    def test_report_rebuilds_a_recorded_runs_report(self, fetched: Path) -> None:
        ran = runner.invoke(app, ["backtest", "--from", "2023-11-01"])
        run_id = re.search(r"^Backtest (\S+):", ran.stdout, re.MULTILINE)
        assert run_id is not None
        page = fetched / "reports" / "backtests" / run_id.group(1) / "report.html"
        page.unlink()

        result = runner.invoke(app, ["report", run_id.group(1)])

        assert result.exit_code == 0, result.output
        assert result.stdout == f"Report: {page}\n"
        assert page.is_file()

    def test_report_explains_a_record_it_cannot_use(self, fetched: Path) -> None:
        ran = runner.invoke(app, ["backtest", "--from", "2023-11-01"])
        run_id = re.search(r"^Backtest (\S+):", ran.stdout, re.MULTILINE)
        assert run_id is not None
        (fetched / "reports" / "backtests" / run_id.group(1) / "metrics.json").unlink()

        result = runner.invoke(app, ["report", run_id.group(1)])

        assert result.exit_code == 1
        assert "metrics.json is missing" in plain(result.stderr)

    def test_a_report_that_cannot_be_written_does_not_fail_the_backtest(
        self, fetched: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(folder: Path) -> Path:
            raise ReportError(f"{folder}: cannot read the record: damaged")

        monkeypatch.setattr(cli, "write_report", broken)

        result = runner.invoke(app, ["backtest", "--from", "2023-11-01"])

        assert result.exit_code == 0, result.output
        assert "Report:        not written:" in result.stdout

    @pytest.mark.parametrize("run_id", ["20231101T000000Z-00000000", "../config", ""])
    def test_report_refuses_a_run_it_cannot_find(self, fetched: Path, run_id: str) -> None:
        result = runner.invoke(app, ["report", run_id])

        assert result.exit_code == 1
        assert (
            f"no backtest, walk-forward, sweep, capital or profile comparison record named "
            f"{run_id!r}"
        ) in plain(result.stderr)

    def test_a_range_reaching_the_holdout_is_refused(self, fetched: Path) -> None:
        result = runner.invoke(app, ["backtest", "--from", "2023-11-01", "--to", "2024-01-05"])

        assert result.exit_code == 1
        assert "2024-01-01 on is the reserved holdout" in plain(result.stderr)
        assert not (fetched / "reports").exists()

    def test_missing_history_says_what_to_fetch(self, fetched: Path) -> None:
        result = runner.invoke(app, ["backtest", "--from", "2023-06-01"])

        assert result.exit_code == 1
        assert "tyche data fetch SPY --exchange ARCX --from 2023-05-03" in plain(result.stderr)

    def test_needs_a_first_date(self, home: Path) -> None:
        result = runner.invoke(app, ["backtest"])

        assert result.exit_code == 2
        assert "--from" in plain(result.output)

    def test_a_run_that_halts_is_recorded_and_fails_the_command(
        self, fetched: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def halting(*args: Any, **kwargs: Any) -> BacktestOutcome:
            outcome = run_configured_backtest(*args, **kwargs)
            halted = replace(outcome.result.run, completed=False, failure="a stage failed")
            return replace(outcome, result=replace(outcome.result, run=halted))

        monkeypatch.setattr(cli, "run_configured_backtest", halting)

        result = runner.invoke(app, ["backtest", "--from", "2023-11-01"])

        assert result.exit_code == 1
        assert ": halted" in result.stdout
        assert "Error: the run halted: a stage failed" in plain(result.stderr)


def fetch_spy_and_qqq(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A new workspace whose cache holds SPY and QQQ from October 2021 to December 2023."""
    nyse = ExchangeCalendarsCalendar("XNYS", first=date(2021, 1, 1), last=date(2024, 1, 31))

    def fake_fetcher(
        cache_dir: Path | None = None,
    ) -> Callable[[str, date, date], list[YahooRow]]:
        def fetch(ticker: str, start: date, end: date) -> list[YahooRow]:
            days = [s.day for s in nyse.sessions_between(start, end) if s.day < end]
            return [row(day, 400.0 + i) for i, day in enumerate(days)]

        return fetch

    monkeypatch.setattr(runtime_data, "yfinance_fetcher", fake_fetcher)
    assert runner.invoke(app, ["init"]).exit_code == 0
    keep_candidates(home / "tyche-workspace", "SPY", "QQQ")
    for symbol, exchange in (("SPY", "ARCX"), ("QQQ", "XNAS")):
        arguments = ["data", "fetch", symbol, "--exchange", exchange]
        result = runner.invoke(app, [*arguments, "--from", "2021-10-01", "--to", "2023-12-29"])
        assert result.exit_code == 0, result.output
    return home / "tyche-workspace"


class TestWalkForward:
    @pytest.fixture
    def fetched(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        return fetch_spy_and_qqq(home, monkeypatch)

    def test_runs_records_and_summarises(self, fetched: Path) -> None:
        result = runner.invoke(app, ["walk-forward", "--from", "2022-01-03", "--train-years", "1"])

        assert result.exit_code == 0, result.output
        out = result.stdout
        assert "Walk-forward, anchored: 1-year first training window, 1-year test windows" in out
        assert re.search(
            r"^  Fold  1 train 2022-01-03 to 2022-12-31  CAGR +\S+%  benchmark +\S+%$",
            out,
            re.MULTILINE,
        )
        assert re.search(
            r"^  Fold  1 test  2023-01-01 to 2023-12-31  return +\S+%  benchmark +\S+%$",
            out,
            re.MULTILINE,
        )
        assert re.search(
            r"^Walk-forward \d{8}T\d{6}Z-[0-9a-f]{8}: completed, 1 of 1 folds$", out, re.MULTILINE
        )
        assert "Out of sample: 2023-01-01 to 2023-12-31, the test windows joined" in out
        assert re.search(r"^    Sharpe \(rf 0\)\s+\S+\s+\S+$", out, re.MULTILINE)
        assert re.search(r"^  Ahead of the benchmark in [01] of 1 test windows$", out, re.MULTILINE)
        record = re.search(r"Record:\s+(\S+)", out)
        assert record is not None
        assert Path(record.group(1)).is_file()
        assert Path(record.group(1)).is_relative_to(fetched / "reports" / "walk_forward")
        report = re.search(r"Report:\s+(\S+)", out)
        assert report is not None
        assert Path(report.group(1)) == Path(record.group(1)).parent / "report.html"
        assert Path(report.group(1)).is_file()

    def test_rolling_windows_keep_their_length(self, fetched: Path) -> None:
        result = runner.invoke(
            app, ["walk-forward", "--from", "2022-01-03", "--train-years", "1", "--rolling"]
        )

        assert result.exit_code == 0, result.output
        assert "Walk-forward, rolling: 1-year training window, 1-year test windows" in result.stdout

    def test_report_rebuilds_a_walk_forwards_report(self, fetched: Path) -> None:
        ran = runner.invoke(app, ["walk-forward", "--from", "2022-01-03", "--train-years", "1"])
        found = re.search(r"^Walk-forward (\S+):", ran.stdout, re.MULTILINE)
        assert found is not None
        page = fetched / "reports" / "walk_forward" / found.group(1) / "report.html"
        page.unlink()

        result = runner.invoke(app, ["report", found.group(1)])

        assert result.exit_code == 0, result.output
        assert result.stdout == f"Report: {page}\n"
        assert page.is_file()

    def test_a_range_with_no_test_window_is_refused(self, fetched: Path) -> None:
        result = runner.invoke(app, ["walk-forward", "--from", "2022-01-03"])

        assert result.exit_code == 1
        assert "leaves no test window after a 5-year training window" in plain(result.stderr)
        assert not (fetched / "reports").exists()

    def test_windows_are_at_least_a_year(self, home: Path) -> None:
        result = runner.invoke(app, ["walk-forward", "--from", "2022-01-03", "--test-years", "0"])

        assert result.exit_code == 2
        assert "--test-years" in plain(result.output)

    def test_a_walk_forward_that_stops_is_recorded_and_fails_the_command(
        self, fetched: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def stopping(*args: Any, **kwargs: Any) -> WalkForwardOutcome:
            outcome = run_configured_walk_forward(*args, **kwargs)
            return replace(outcome, metrics=None, failure="fold 1's test window halted: oops")

        monkeypatch.setattr(cli, "run_configured_walk_forward", stopping)

        result = runner.invoke(app, ["walk-forward", "--from", "2022-01-03", "--train-years", "1"])

        assert result.exit_code == 1
        assert ": stopped, 1 of 1 folds" in result.stdout
        assert "Report:" not in result.stdout
        assert "Error: the walk-forward stopped: fold 1's test window halted: oops" in plain(
            result.stderr
        )


ROTATION_ON_TWO = """plugin = "trend_rotation"

[parameters]
holdings = 1
momentum_sessions = 20
trend_sessions = 50
instruments = [
    { symbol = "SPY", exchange = "ARCX", asset_class = "etf" },
    { symbol = "QQQ", exchange = "XNAS", asset_class = "etf" },
]
"""


class TestSweep:
    @pytest.fixture
    def fetched(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A workspace running the trend rotation over SPY and QQQ, cached from October
        2021 to December 2023, with a sweep of four combinations named ``small``."""
        workspace = fetch_spy_and_qqq(home, monkeypatch)
        tyche = workspace / "config" / "tyche.toml"
        text = tyche.read_text(encoding="utf-8")
        tyche.write_text(text.replace('buy_and_hold = "1.0"', 'trend_rotation = "1.0"'))
        (workspace / "config/strategies/trend_rotation.toml").write_text(ROTATION_ON_TWO)
        (workspace / "config/sweeps/small.toml").write_text(
            'strategy = "trend_rotation"\n[grid]\nholdings = [1, 2]\nmomentum_sessions = [10, 40]\n'
        )
        return workspace

    def test_runs_records_and_summarises(self, fetched: Path) -> None:
        result = runner.invoke(app, ["sweep", "small", "--from", "2022-06-01"])

        assert result.exit_code == 0, result.output
        out = result.stdout
        assert (
            "Sweep small: 4 combinations of trend_rotation (trend_rotation); 4 trials counted "
            "with the 0 already recorded" in out
        )
        assert re.search(
            r"^  Trial   1/4  holdings=1 momentum_sessions=10  Sharpe +\S+  CAGR +\S+%$",
            out,
            re.MULTILINE,
        )
        assert re.search(r"^Sweep \d{8}T\d{6}Z-[0-9a-f]{8}: 4 trials, 4 measured$", out, re.M)
        assert re.search(
            r"^  Pick:          trial \d, holdings=\d momentum_sessions=\d+ \(in-sample\)$",
            out,
            re.M,
        )
        assert re.search(r"^  Deflated Sharpe ratio: \d+\.\d% after 4 trials", out, re.M)
        report = re.search(r"Report:\s+(\S+)", out)
        assert report is not None
        assert Path(report.group(1)).is_file()
        assert Path(report.group(1)).is_relative_to(fetched / "reports" / "sweeps")

    def test_a_strategy_without_a_budget_is_refused(self, home: Path) -> None:
        assert runner.invoke(app, ["init"]).exit_code == 0

        result = runner.invoke(app, ["sweep", "trend_rotation", "--from", "2022-06-01"])

        assert result.exit_code == 1
        assert "'trend_rotation' has no budget under [strategies]" in plain(result.stderr)

    def test_report_rebuilds_a_sweeps_report(self, fetched: Path) -> None:
        ran = runner.invoke(app, ["sweep", "small", "--from", "2022-06-01"])
        found = re.search(r"^Sweep (\d\S+):", ran.stdout, re.MULTILINE)
        assert found is not None
        page = fetched / "reports" / "sweeps" / found.group(1) / "report.html"
        page.unlink()

        result = runner.invoke(app, ["report", found.group(1)])

        assert result.exit_code == 0, result.output
        assert result.stdout == f"Report: {page}\n"

    def test_a_walk_forward_can_pick_from_a_sweep(self, fetched: Path) -> None:
        result = runner.invoke(
            app,
            ["walk-forward", "--from", "2022-01-03", "--train-years", "1", "--sweep", "small"],
        )

        assert result.exit_code == 0, result.output
        assert "  Train step: sweep small (config/sweeps/small.toml), highest Sharpe ratio" in (
            result.stdout
        )
        assert re.search(
            r"^  Fold  1 train 2022-01-03 to 2022-12-31  picked holdings=\d momentum_sessions=\d+$",
            result.stdout,
            re.MULTILINE,
        )


class TestCapital:
    def test_runs_records_and_summarises(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workspace = fetch_spy_and_qqq(home, monkeypatch)

        result = runner.invoke(
            app,
            ["capital", "--from", "2022-06-01", "--amounts", "300,5000", "--reference", "100000"],
        )

        assert result.exit_code == 0, result.output
        out = result.stdout
        assert re.search(
            r"^  buy_and_hold +IBKR Pro Fixed +100,000  CAGR +\S+%  costs +\S+% a year  "
            r"\(reference\)$",
            out,
            re.MULTILINE,
        )
        assert re.search(r"^  buy_and_hold +IBKR Pro Tiered +300  .* penalty +[+-]", out, re.M)
        assert re.search(r"^Capital \d{8}T\d{6}Z-[0-9a-f]{8}: minimum viable capital", out, re.M)
        assert re.search(
            r"^  buy_and_hold +IBKR Pro Fixed +(none of the amounts tested|[\d,]+ USD); "
            r"reference Sharpe \S+, benchmark \S+$",
            out,
            re.M,
        )
        report = re.search(r"Report:\s+(\S+)", out)
        assert report is not None
        assert Path(report.group(1)).is_relative_to(workspace / "reports" / "capital")

        found = re.search(r"^Capital (\d\S+):", out, re.MULTILINE)
        assert found is not None
        page = Path(report.group(1))
        page.unlink()
        rebuilt = runner.invoke(app, ["report", found.group(1)])
        assert rebuilt.exit_code == 0, rebuilt.output
        assert rebuilt.stdout == f"Report: {page}\n"

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["--amounts", "500,abc"], "--amounts: not a number: 'abc'"),
            (["--amounts", "5000,500"], "give the amounts smallest first"),
            (["--tolerance", "-1"], "the tolerance must be at least 0"),
        ],
    )
    def test_a_bad_request_is_refused_before_anything_runs(
        self, home: Path, arguments: list[str], message: str
    ) -> None:
        assert runner.invoke(app, ["init"]).exit_code == 0

        result = runner.invoke(app, ["capital", "--from", "2022-06-01", *arguments])

        assert result.exit_code == 1
        assert message in plain(result.stderr)
        assert not (home / "tyche-workspace" / "reports" / "capital").exists()


class TestKillAndResume:
    """`tyche kill` and `tyche resume` (ADR-0039)."""

    def workspace(self) -> Workspace:
        runner.invoke(app, ["init"])
        return Workspace(Path.home() / "tyche-workspace")

    def test_kill_engages_the_switch_and_says_what_it_does(self, home: Path) -> None:
        workspace = self.workspace()

        result = runner.invoke(app, ["kill", "--reason", "looks wrong"])

        assert result.exit_code == 0, result.output
        assert "Kill switch engaged" in result.stdout
        assert "Reason: looks wrong" in result.stdout
        assert "holdings are kept; stops already resting stay" in result.stdout
        assert "No paper or live run has saved state yet" in result.stdout
        assert FlagFileKillSwitch(workspace.kill_file).read() is not None

    def test_a_flatten_asks_first(self, home: Path) -> None:
        workspace = self.workspace()

        refused = runner.invoke(app, ["kill", "--flatten"], input="n\n")
        assert refused.exit_code == 1
        assert not workspace.kill_file.exists()

        result = runner.invoke(app, ["kill", "--flatten"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "every holding is sold at the next decision" in result.stdout
        kill = FlagFileKillSwitch(workspace.kill_file).read()
        assert kill is not None
        assert kill.flatten

    def test_kill_lists_the_orders_left_working_and_the_halt(self, home: Path) -> None:
        workspace = self.workspace()
        save(workspace, checkpoints.checkpoint())

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert "halted by the drawdown kill since 2024-01-03" in result.stdout
        assert "20240103T210000Z-SPY.ARCX-buy: buy 3 SPY.ARCX market, day" in result.stdout
        assert "sim-000001-stop-alpha: sell 6 SPY.ARCX stop at 440" in result.stdout
        assert "They are not cancelled" in result.stdout

    def test_kill_twice_without_flatten_keeps_a_flatten(self, home: Path) -> None:
        self.workspace()
        runner.invoke(app, ["kill", "--flatten", "--yes"])

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert "was already engaged" in result.stdout
        assert "only `tyche resume` releases it" in result.stdout

    def test_kill_refuses_a_folder_that_is_not_a_workspace(self, home: Path) -> None:
        result = runner.invoke(app, ["kill", "--home", str(home / "nowhere")])

        assert result.exit_code == 1
        assert "no workspace at" in result.stderr
        assert not (home / "nowhere" / "KILL").exists()

    def test_resume_shows_what_it_lifts_and_asks(self, home: Path) -> None:
        workspace = self.workspace()
        save(workspace, checkpoints.checkpoint())
        runner.invoke(app, ["kill", "--reason", "stop"])

        refused = runner.invoke(app, ["resume", "--reason", "ok"], input="n\n")
        assert refused.exit_code == 1
        assert workspace.kill_file.exists()

        result = runner.invoke(app, ["resume", "--reason", "ok"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "Drawdown halt since 2024-01-03" in result.stdout
        assert "the next close becomes the new peak" in result.stdout
        assert "Lifted the kill switch and the drawdown halt." in result.stdout
        assert "Recorded as run resume-" in result.stdout
        assert not workspace.kill_file.exists()

    def test_resume_shows_and_applies_a_reconciliation_halt(self, home: Path) -> None:
        workspace = self.workspace()
        save(workspace, unreconciled())

        killed = runner.invoke(app, ["kill", "--reason", "look first"])
        assert "Trading is also halted by reconciliation since 2024-01-04" in killed.stdout

        result = runner.invoke(app, ["resume", "--reason", "stop hit overnight", "--yes"])

        assert result.exit_code == 0, result.output
        assert "Reconciliation halt since 2024-01-04 00:15 UTC:" in result.stdout
        assert "Resuming applies: order sim-000001-stop-alpha sold 6 SPY" in result.stdout
        assert "Lifted the kill switch and the reconciliation halt." in result.stdout
        assert "Applied: order sim-000001-stop-alpha sold 6" in result.stdout

    def test_resume_with_nothing_to_lift(self, home: Path) -> None:
        self.workspace()

        result = runner.invoke(app, ["resume", "--reason", "ok"])

        assert result.exit_code == 0, result.output
        assert "Nothing to resume" in result.stdout

    def test_resume_needs_a_reason(self, home: Path) -> None:
        self.workspace()

        result = runner.invoke(app, ["resume"])

        assert result.exit_code == 2


WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/secret-token"


class RecordingNotifier:
    """Stands in for the Discord notifier: records what it is asked to send."""

    sent: ClassVar[list[Alert]] = []
    failure: ClassVar[str | None] = None

    def __init__(self, webhook_url: SecretStr, *, code_version: str) -> None:
        assert webhook_url.get_secret_value() == WEBHOOK
        assert code_version == tyche.__version__

    def send(self, alert: Alert) -> None:
        if RecordingNotifier.failure is not None:
            raise NotifierError(RecordingNotifier.failure)
        RecordingNotifier.sent.append(alert)


class TestAlertsAndLogs:
    """Discord alerts from `tyche kill`, `tyche resume` and `tyche notify test`; logs (ADR-0040)."""

    @pytest.fixture(autouse=True)
    def recording(self, monkeypatch: pytest.MonkeyPatch) -> None:
        RecordingNotifier.sent = []
        RecordingNotifier.failure = None
        monkeypatch.setattr("tyche.runtime.notify.DiscordWebhookNotifier", RecordingNotifier)

    def workspace(self, *, webhook: bool = True) -> Workspace:
        runner.invoke(app, ["init"])
        workspace = Workspace(Path.home() / "tyche-workspace")
        if webhook:
            text = workspace.env_file.read_text().replace(
                "DISCORD_WEBHOOK_URL=", f"DISCORD_WEBHOOK_URL={WEBHOOK}"
            )
            workspace.env_file.write_text(text)
        return workspace

    def logged(self, workspace: Workspace) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        for path in sorted(workspace.logs_dir.glob("*.jsonl")):
            text = path.read_text()
            assert "secret-token" not in text
            lines.extend(json.loads(line) for line in text.splitlines())
        return lines

    def test_kill_posts_an_alert(self, home: Path) -> None:
        self.workspace()

        result = runner.invoke(app, ["kill", "--reason", "looks wrong"])

        assert result.exit_code == 0, result.output
        assert "Discord: 1 alert sent." in result.stdout
        [alert] = RecordingNotifier.sent
        assert alert.kind is AlertKind.KILL_SWITCH
        assert alert.lines[0] == "Reason: looks wrong"

    def test_kill_again_unchanged_posts_nothing(self, home: Path) -> None:
        self.workspace()
        runner.invoke(app, ["kill"])

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert len(RecordingNotifier.sent) == 1
        assert "Discord" not in result.stdout

    def test_kill_without_a_webhook_says_so(self, home: Path) -> None:
        self.workspace(webhook=False)

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert "Discord: not set up (DISCORD_WEBHOOK_URL is empty)" in result.stdout

    def test_a_discord_failure_never_fails_the_kill(self, home: Path) -> None:
        workspace = self.workspace()
        RecordingNotifier.failure = "cannot reach Discord: timed out"

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert "1 not sent: cannot reach Discord: timed out" in result.stderr
        assert FlagFileKillSwitch(workspace.kill_file).read() is not None

    def test_a_broken_env_never_fails_the_kill(self, home: Path) -> None:
        workspace = self.workspace()
        workspace.env_file.write_text("NOT_A_KEY=1\n")

        result = runner.invoke(app, ["kill"])

        assert result.exit_code == 0, result.output
        assert "unknown key NOT_A_KEY" in result.stderr
        assert workspace.kill_file.exists()

    def test_resume_posts_an_alert(self, home: Path) -> None:
        self.workspace()
        runner.invoke(app, ["kill"])

        result = runner.invoke(app, ["resume", "--reason", "checked", "--yes"])

        assert result.exit_code == 0, result.output
        assert [a.kind for a in RecordingNotifier.sent] == [
            AlertKind.KILL_SWITCH,
            AlertKind.RESUMED,
        ]
        assert RecordingNotifier.sent[1].lines[0] == "Reason: checked"

    def test_notify_test_sends_a_check(self, home: Path) -> None:
        self.workspace()

        result = runner.invoke(app, ["notify", "test"])

        assert result.exit_code == 0, result.output
        assert "test message sent" in result.stdout
        assert [a.kind for a in RecordingNotifier.sent] == [AlertKind.TEST]

    def test_notify_test_without_a_webhook_fails(self, home: Path) -> None:
        self.workspace(webhook=False)

        result = runner.invoke(app, ["notify", "test"])

        assert result.exit_code == 1
        assert "DISCORD_WEBHOOK_URL is not set" in result.stderr

    def test_notify_test_reports_a_failure(self, home: Path) -> None:
        self.workspace()
        RecordingNotifier.failure = "Discord refused the webhook (HTTP 404)"

        result = runner.invoke(app, ["notify", "test"])

        assert result.exit_code == 1
        assert "HTTP 404" in result.stderr

    def test_config_check_reports_the_webhook(self, home: Path) -> None:
        self.workspace(webhook=False)
        result = runner.invoke(app, ["config", "check"])
        assert "Secrets:        Discord webhook not set: alerts are not sent" in result.stdout

    def test_config_check_reports_the_gateway_without_the_account_id(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.workspace(webhook=False)
        result = runner.invoke(app, ["config", "check"])
        assert "IB Gateway not set, needed from the first paper run" in result.stdout
        assert "IBKR_PORT, IBKR_ACCOUNT_ID" in result.stdout

        monkeypatch.setenv("IBKR_PORT", "4002")
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "TEST-PAPER-1")
        result = runner.invoke(app, ["config", "check"])
        assert "IB Gateway 127.0.0.1:4002, client id 1, account id set" in result.stdout
        assert "TEST-PAPER-1" not in result.stdout

    def test_config_check_refuses_a_broken_env(self, home: Path) -> None:
        workspace = self.workspace()
        workspace.env_file.write_text("DISCORD_WEBHOOK_URL=https://example.com/hook\n")

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 1
        assert "not a Discord webhook URL" in result.stderr
        assert "example.com" not in result.stderr

    def test_config_check_warns_when_env_is_not_private(self, home: Path) -> None:
        workspace = self.workspace()
        workspace.env_file.chmod(0o644)

        result = runner.invoke(app, ["config", "check"])

        assert result.exit_code == 0, result.output
        assert "Discord webhook set" in result.stdout
        assert "other users can read .env" in result.stdout

    def test_commands_log_to_the_workspace_without_secrets(self, home: Path) -> None:
        workspace = self.workspace()

        runner.invoke(app, ["kill", "--reason", "looks wrong"])
        runner.invoke(app, ["notify", "test"])

        entries = self.logged(workspace)
        started = [e["command"] for e in entries if e["message"] == "command started"]
        assert started == ["kill", "notify test"]
        assert any(e["message"] == "kill switch engaged" for e in entries)
        assert [e["alert"] for e in entries if e["message"] == "alert sent"] == [
            "kill_switch",
            "test",
        ]

    def test_a_failing_command_logs_why(self, home: Path) -> None:
        workspace = self.workspace(webhook=False)

        runner.invoke(app, ["notify", "test"])

        failed = [e for e in self.logged(workspace) if e["level"] == "ERROR"]
        assert failed[0]["message"].startswith("command failed: DISCORD_WEBHOOK_URL is not set")

    def test_no_logs_folder_for_a_folder_that_is_not_a_workspace(self, home: Path) -> None:
        runner.invoke(app, ["config", "check", "--home", str(home / "nowhere")])
        assert not (home / "nowhere").exists()


class TestPaperRun:
    """`tyche paper run` (ADR-0045). The cycle itself is tested in tests/runtime."""

    def test_needs_the_ib_gateway_connection(self, home: Path) -> None:
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["paper", "run"])

        assert result.exit_code == 1
        assert "the IB Gateway connection needs" in result.stderr
        assert "IBKR_ACCOUNT_ID" in result.stderr

    def test_says_what_the_cycle_did(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        runner.invoke(app, ["init"])
        outcome = PaperOutcome(
            check_run="paper-20240206T233000Z-check",
            first_run=True,
            startup=Reconciliation(at=datetime(2024, 2, 6, 23, 30, tzinfo=UTC)),
            failure="IBKRConnectionError: cannot connect to IB Gateway at 127.0.0.1:4002",
        )
        monkeypatch.setattr(cli, "run_paper", lambda config, **_: outcome)

        result = runner.invoke(app, ["paper", "run"])

        assert result.exit_code == 1
        assert "First paper run: Tyche started from IBKR's cash." in result.stdout
        assert "reconciliation match" in result.stdout
        assert "cannot connect to IB Gateway" in result.stderr


class TestUi:
    """`tyche ui` (ADR-0046). The API itself is tested in tests/api."""

    def test_needs_the_built_page(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner.invoke(app, ["init"])
        monkeypatch.setattr(cli, "default_app_dir", lambda: tmp_path / "missing")

        result = runner.invoke(app, ["ui", "--no-browser"])

        assert result.exit_code == 1
        assert "run `make ui`" in result.stderr

    def test_serves_on_127_0_0_1_with_a_new_token(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner.invoke(app, ["init"])
        built = tmp_path / "dist"
        built.mkdir()
        (built / "index.html").write_text("<html></html>")
        monkeypatch.setattr(cli, "default_app_dir", lambda: built)
        served: list[int] = []
        opened: list[str] = []
        monkeypatch.setattr(cli, "serve", lambda console, port: served.append(port))
        monkeypatch.setattr("webbrowser.open", opened.append)

        result = runner.invoke(app, ["ui", "--port", "9123"])

        assert result.exit_code == 0, result.output
        assert served == [9123]
        (address,) = opened
        assert address.startswith("http://127.0.0.1:9123/#token=")
        assert address in result.stdout
        token = address.split("#token=")[1]
        assert len(token) >= 40
        again = runner.invoke(app, ["ui", "--port", "9123"])
        assert opened[-1] != address  # a new token at every launch
        assert again.exit_code == 0

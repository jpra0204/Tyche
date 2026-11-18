"""The `tyche` command: version, init and config check, run as a user would."""

import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tyche
from tests.adapters.data.test_yfinance_source import row
from tests.support.market import JANUARY_2024
from tyche.adapters.data.yfinance_source import UnknownSymbolError, YahooRow
from tyche.cli import app
from tyche.runtime import data as runtime_data

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
        assert "buy_and_hold (buy_and_hold), budget 1.0" in result.stdout
        assert "cash:" not in result.stdout
        assert "Config hash:    sha256:" in result.stdout

    def test_lists_the_cash_left_after_budgets(self, home: Path) -> None:
        runner.invoke(app, ["init"])
        config_file = home / "tyche-workspace" / "config" / "tyche.toml"
        config_file.write_text(
            'schema_version = 1\nmarket_profile = "US"\n[strategies]\nbuy_and_hold = "0.8"\n'
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

"""The `tyche` command: version, init and config check, run as a user would."""

import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tyche
from tyche.cli import app

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
        assert "Config hash:    sha256:" in result.stdout

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

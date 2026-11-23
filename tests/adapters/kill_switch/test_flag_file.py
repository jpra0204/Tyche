"""The KILL flag file: what engages it, what it says, and that it fails closed (ADR-0039)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tyche.adapters.kill_switch import FlagFileKillSwitch, engage, release
from tyche.adapters.kill_switch.flag_file import parse
from tyche.core.domain import Kill

AT = datetime(2026, 11, 23, 21, 4, 5, 123456, tzinfo=UTC)


def switch(tmp_path: Path) -> FlagFileKillSwitch:
    return FlagFileKillSwitch(tmp_path / "KILL")


def test_no_file_is_off(tmp_path: Path) -> None:
    assert switch(tmp_path).read() is None


def test_an_empty_file_made_by_hand_engages_it_without_flatten(tmp_path: Path) -> None:
    (tmp_path / "KILL").touch()
    found = switch(tmp_path).read()
    assert found is not None
    assert not found.flatten
    assert found.engaged_at is None
    assert "by hand" in found.reason


def test_what_engage_writes_reads_back_to_the_second(tmp_path: Path) -> None:
    engage(tmp_path / "KILL", Kill('market "chaos"\\ é', flatten=True, engaged_at=AT))
    assert switch(tmp_path).read() == Kill(
        'market "chaos"\\ é', flatten=True, engaged_at=AT.replace(microsecond=0)
    )
    assert not (tmp_path / ".KILL.writing").exists()


def test_engage_replaces_what_is_there(tmp_path: Path) -> None:
    engage(tmp_path / "KILL", Kill("first"))
    engage(tmp_path / "KILL", Kill("second", flatten=True))
    assert switch(tmp_path).read() == Kill("second", flatten=True)


def test_release_removes_it_once(tmp_path: Path) -> None:
    engage(tmp_path / "KILL", Kill("x"))
    assert release(tmp_path / "KILL")
    assert switch(tmp_path).read() is None
    assert not release(tmp_path / "KILL")


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("flatten = true\nreason = ", "not valid TOML"),
        ("flatten = true\nwhy = 'x'\n", "unknown keys: why"),
        ('flatten = "yes"\n', "flatten is not true or false"),
        ("flatten = 1\n", "flatten is not true or false"),
        ("flatten = true\nreason = 3\n", "reason is not a text"),
        ("flatten = true\nreason = ' '\n", "reason is not a text"),
        ("flatten = true\nengaged_at = 'today'\n", "engaged_at is not a date and time"),
        ("flatten = true\nengaged_at = 2026-11-23T21:04:00\n", "UTC"),
        ("flatten = true\nengaged_at = 2026-11-23T21:04:00+01:00\n", "UTC"),
    ],
)
def test_anything_unexpected_engages_it_and_never_flattens(text: str, why: str) -> None:
    found = parse(text)
    assert not found.flatten
    assert why in found.reason
    assert "engaged without flatten" in found.reason


def test_a_file_that_cannot_be_read_engages_it(tmp_path: Path) -> None:
    (tmp_path / "KILL").write_bytes(b"\xff\xfe flatten = true")
    found = switch(tmp_path).read()
    assert found is not None
    assert not found.flatten
    assert "cannot be read" in found.reason


def test_a_folder_named_kill_engages_it(tmp_path: Path) -> None:
    (tmp_path / "KILL").mkdir()
    found = switch(tmp_path).read()
    assert found is not None
    assert not found.flatten

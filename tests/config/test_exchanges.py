"""The known-exchanges table and the workspace's data folder."""

from pathlib import Path

from tyche.config import KNOWN_EXCHANGES, Workspace
from tyche.core.domain import Currency


def test_every_known_exchange_is_a_us_listing_on_the_new_york_calendar() -> None:
    assert sorted(KNOWN_EXCHANGES) == ["ARCX", "BATS", "XASE", "XNAS", "XNYS"]
    for mic, info in KNOWN_EXCHANGES.items():
        assert info.mic == mic
        assert info.currency is Currency.USD
        assert info.calendar == "XNYS"


def test_market_data_lives_in_the_workspace_data_folder(tmp_path: Path) -> None:
    assert Workspace(tmp_path).data_dir == tmp_path / "data"

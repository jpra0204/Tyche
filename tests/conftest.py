"""Shared test configuration."""

from collections.abc import Iterator

import pytest
from hypothesis import settings

from tyche.adapters.logs import close_logging
from tyche.config import KNOWN_KEYS

# Property-based tests must be repeatable like every other test: the same examples on
# every run and every machine. A failing example is printed, so it can become a
# regular test.
settings.register_profile("tyche", derandomize=True, database=None, deadline=None, max_examples=200)
settings.load_profile("tyche")


@pytest.fixture(autouse=True)
def _no_secrets_and_no_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test reads a real secret, and none leaves Tyche's log files open.

    A developer's shell may export ``DISCORD_WEBHOOK_URL``; without this, a test of
    ``tyche kill`` would post to the real channel.
    """
    for key in KNOWN_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    close_logging()

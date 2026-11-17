"""System events: the life of a run."""

from dataclasses import dataclass
from enum import StrEnum

from tyche.core.events.event import Event


class RunMode(StrEnum):
    """Which world a run is connected to. Recorded, never used to change behaviour (ADR-0005)."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class RunStage(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class RunEvent(Event):
    """A run started or completed.

    A run that fails cannot announce it on the bus, because the bus has halted. The
    engine reports a failure in its ``RunResult`` instead.

    Attributes:
        run_id: Identifies the run in the journal and in reports.
        mode: Backtest, paper or live.
        stage: Started or completed.
        config_hash: Fingerprint of the configuration used, when there is one.
        code_version: Tyche's version.
    """

    run_id: str
    mode: RunMode
    stage: RunStage
    code_version: str
    config_hash: str | None = None

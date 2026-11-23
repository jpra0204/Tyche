"""System events: the life of a run, and Pablo's hand on it."""

from dataclasses import dataclass
from enum import StrEnum

from tyche.core.domain import AccountTrigger, Kill, RiskRule
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


@dataclass(frozen=True, slots=True)
class ResumeEvent(Event):
    """Pablo lifted the kill switch, the drawdown halt, or both: ``tyche resume`` (ADR-0039).

    Journaled as a run of its own, with this one event, so the state database records
    every manual restart. When it lifts a halt, the run also saves a checkpoint: the
    latest one's state with the halt lifted and the peak forgotten.

    Attributes:
        reason: Why, as Pablo gave it.
        kill: The kill switch released, or ``None`` if it was not engaged.
        halt: The drawdown halt lifted, or ``None`` if trading was not halted.
        after_run: The run whose checkpoint held the halt, or ``None``.
    """

    reason: str
    kill: Kill | None = None
    halt: AccountTrigger | None = None
    after_run: str | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("ResumeEvent: needs a reason")
        if self.kill is None and self.halt is None:
            raise ValueError("ResumeEvent: lifts nothing")
        if self.halt is not None:
            if self.halt.rule is not RiskRule.DRAWDOWN_KILL:
                raise ValueError(f"ResumeEvent: only the drawdown kill halts, not {self.halt.rule}")
            if self.after_run is None:
                raise ValueError("ResumeEvent: a lifted halt needs the run that held it")

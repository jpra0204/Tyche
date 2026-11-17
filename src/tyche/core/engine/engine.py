"""The engine: one run loop for backtest, paper and live (ADR-0005).

The loop is three lines long on purpose::

    for each input from the feed:
        move the clock to the input's moment
        publish the input, then drain the bus (run to completion, ADR-0003)

Everything else (strategies, risk, orders, the journal) happens in subscribers.
"""

from dataclasses import dataclass

from tyche.core.events import BusError, EventBus, RunEvent, RunMode, RunStage
from tyche.core.ports import Feed, PacedClock

SOURCE = "engine"


class FeedOrderError(Exception):
    """The feed produced an input earlier than the clock. The feed has a bug."""


@dataclass(frozen=True, slots=True)
class RunResult:
    """How a run ended.

    Attributes:
        run_id: The run's identifier.
        completed: True if every input was handled and the run completed.
        inputs: Inputs taken from the feed and handled.
        events: Events handled, including everything the inputs caused.
        failure: Why the run stopped, when it did not complete.
    """

    run_id: str
    completed: bool
    inputs: int
    events: int
    failure: str | None = None


class Engine:
    """Runs a feed through an event bus whose subscribers are already wired.

    The engine does not know which mode it is in: the clock and the feed decide that.
    ``mode`` is only recorded in the ``RunEvent`` for the journal.

    A failing subscriber halts the bus (fail closed). The engine then stops taking
    inputs and reports the failure in its ``RunResult``; it does not raise.
    """

    def __init__(
        self,
        bus: EventBus,
        clock: PacedClock,
        *,
        run_id: str,
        mode: RunMode,
        code_version: str,
        config_hash: str | None = None,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._run_id = run_id
        self._mode = mode
        self._code_version = code_version
        self._config_hash = config_hash

    def run(self, feed: Feed) -> RunResult:
        inputs = 0
        events = 0
        try:
            events += self._announce(RunStage.STARTED)
            for item in feed.inputs():
                now = self._clock.now()
                if item.at < now:
                    raise FeedOrderError(
                        f"the feed produced an input at {item.at.isoformat()} after the clock "
                        f"had reached {now.isoformat()}"
                    )
                self._clock.wait_until(item.at)
                self._bus.publish(item.event, source=item.source, cycle_id=item.cycle_id)
                events += self._bus.drain()
                inputs += 1
            events += self._announce(RunStage.COMPLETED)
        except (BusError, FeedOrderError) as error:
            return RunResult(self._run_id, False, inputs, events, str(error))
        return RunResult(self._run_id, True, inputs, events)

    def _announce(self, stage: RunStage) -> int:
        self._bus.publish(
            RunEvent(
                run_id=self._run_id,
                mode=self._mode,
                stage=stage,
                code_version=self._code_version,
                config_hash=self._config_hash,
            ),
            source=SOURCE,
        )
        return self._bus.drain()

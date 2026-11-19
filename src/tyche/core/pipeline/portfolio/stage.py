"""PortfolioStage: pipeline stage 4, every strategy's wishes as one proposed portfolio.

At each decision cycle the stage collects the ``SignalEvent``s, and on the
``SignalsReadyEvent`` publishes one ``TargetPortfolioEvent`` (ADR-0022):

* one ``Sleeve`` per strategy with a budget, saying whether it decided or failed and
  which instruments it decided on;
* one ``InstrumentTarget`` per instrument some strategy targeted, adding up each
  strategy's ``budget * weight`` as a ``Contribution`` that keeps its own stop.

The stage keeps nothing between cycles. "Keep what you hold" is said by the event
itself (an instrument outside a sleeve's ``decided_on``, or a failed sleeve), so a
restart cannot turn a hold into a sale.

A ``SignalsReadyEvent`` that does not match the budgets, or a signal from another
decision time, is a wiring bug: the run halts (fail closed, ADR-0003).
"""

from collections.abc import Mapping
from decimal import Decimal

from tyche.core.domain import (
    Contribution,
    Instrument,
    InstrumentTarget,
    Sleeve,
    SleeveStatus,
    require_budgets,
)
from tyche.core.events import (
    Envelope,
    EventBus,
    SignalEvent,
    SignalsReadyEvent,
    TargetPortfolioEvent,
)

SUBSCRIBER = "portfolio"


class PortfolioError(Exception):
    """The stage's inputs do not match its budgets or each other. A wiring bug."""


class PortfolioStage:
    """Pipeline stage 4. Publishes a ``TargetPortfolioEvent`` for every ``SignalsReadyEvent``.

    Args:
        bus: The run's event bus.
        budgets: Each strategy's fraction of account equity, above 0 and at most 1,
            adding up to at most 1. Every strategy the signals stage asks must have one.
    """

    def __init__(self, bus: EventBus, budgets: Mapping[str, Decimal]) -> None:
        try:
            require_budgets(budgets)
        except ValueError as error:
            raise PortfolioError(str(error)) from error
        self._bus = bus
        self._budgets = dict(budgets)
        self._pending: dict[str, SignalEvent] = {}
        bus.subscribe(SignalEvent, self._on_signal, name=SUBSCRIBER)
        bus.subscribe(SignalsReadyEvent, self._on_ready, name=SUBSCRIBER)

    def _on_signal(self, envelope: Envelope[SignalEvent]) -> None:
        signal = envelope.event
        if signal.strategy_id not in self._budgets:
            raise PortfolioError(f"a signal from {signal.strategy_id}, which has no budget")
        if signal.strategy_id in self._pending:
            raise PortfolioError(
                f"two signals from {signal.strategy_id} before the cycle's SignalsReadyEvent"
            )
        self._pending[signal.strategy_id] = signal

    def _on_ready(self, envelope: Envelope[SignalsReadyEvent]) -> None:
        ready = envelope.event
        signals, self._pending = self._pending, {}
        failed = {f.strategy_id: f.error for f in ready.failed}
        named = set(ready.reported) | set(failed)
        if named != set(self._budgets):
            raise PortfolioError(
                f"strategies asked {sorted(named)} do not match strategies with a budget "
                f"{sorted(self._budgets)}"
            )
        if set(signals) != set(ready.reported):
            raise PortfolioError(
                f"signals received from {sorted(signals)}, but {sorted(ready.reported)} reported"
            )

        sleeves: list[Sleeve] = []
        contributions: dict[Instrument, list[Contribution]] = {}
        for strategy_id in sorted(self._budgets):
            budget = self._budgets[strategy_id]
            if strategy_id in failed:
                sleeves.append(
                    Sleeve(strategy_id, budget, SleeveStatus.FAILED, error=failed[strategy_id])
                )
                continue
            signal = signals[strategy_id]
            if signal.as_of != ready.as_of:
                raise PortfolioError(
                    f"{strategy_id}'s signal is for {signal.as_of.isoformat()}, the cycle for "
                    f"{ready.as_of.isoformat()}"
                )
            sleeves.append(
                Sleeve(
                    strategy_id,
                    budget,
                    SleeveStatus.DECIDED,
                    decided_on=signal.offered,
                    strategy_version=signal.strategy_version,
                )
            )
            for target in signal.targets:
                contributions.setdefault(target.instrument, []).append(
                    Contribution(
                        strategy_id, budget * target.weight, target.reason, target.stop_price
                    )
                )

        targets = tuple(
            InstrumentTarget(instrument, tuple(contributions[instrument]))
            for instrument in sorted(contributions, key=lambda i: (i.symbol, i.exchange))
        )
        self._bus.publish(TargetPortfolioEvent(ready.as_of, tuple(sleeves), targets))

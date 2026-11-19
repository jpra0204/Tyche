"""The risk gate (pipeline stage 5): the only publisher of ``ApprovedPortfolioEvent``.

Execution acts on nothing else (ADR-0006), so every order passes through here by
construction. Phase 1 has no risk rules yet: ``PassThroughGate`` approves each proposed
portfolio exactly as proposed. It exists now so that the event flow is already the
final one, and Phase 2 adds the rules (risk per trade, position caps, the daily loss
limit, the drawdown kill switch) inside the gate without touching execution.
"""

from tyche.core.events import (
    ApprovedPortfolioEvent,
    Envelope,
    EventBus,
    TargetPortfolioEvent,
)

SUBSCRIBER = "risk"
PASS_THROUGH = "pass-through"
"""The profile name recorded on every portfolio this gate approves."""


class PassThroughGate:
    """Approves every proposed portfolio unchanged. Phase 1 only.

    Args:
        bus: The run's event bus.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe(TargetPortfolioEvent, self._on_target, name=SUBSCRIBER)

    def _on_target(self, envelope: Envelope[TargetPortfolioEvent]) -> None:
        proposed = envelope.event
        self._bus.publish(
            ApprovedPortfolioEvent(
                as_of=proposed.as_of,
                sleeves=proposed.sleeves,
                targets=proposed.targets,
                profile=PASS_THROUGH,
            )
        )

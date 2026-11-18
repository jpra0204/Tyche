"""Trading events: orders, fills and cash distributions.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass

from tyche.core.domain import CashDistribution, Fill, OrderState
from tyche.core.events.event import Event


@dataclass(frozen=True, slots=True)
class OrderEvent(Event):
    """An order changed status. One event per transition of its lifecycle.

    Execution publishes the ``SUBMITTED`` state; the broker publishes every status
    after that, with the reason in ``state.note`` when there is one.
    """

    state: OrderState


@dataclass(frozen=True, slots=True)
class FillEvent(Event):
    """Shares changed hands. Published by the broker, before the order's new status."""

    fill: Fill


@dataclass(frozen=True, slots=True)
class DistributionEvent(Event):
    """A cash distribution goes ex: holders at the previous close are owed the cash.

    Published by the feed at the open of the ex-date session, before that session's
    bars, so the broker sees who held the shares at the previous close.
    """

    distribution: CashDistribution

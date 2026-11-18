"""ScreeningStage: pipeline stage 2, which eligible instruments come first.

A screen scores each member of the universe; the stage ranks the members by score,
best first, and optionally keeps only the top few. Ties are broken by symbol and then
exchange, so the same inputs always give the same ranking.

A screen sees only what the universe measured (``UniverseMember``). That is enough for
ranking by liquidity. Screens that need more price history wait for PR 12, which
decides how strategies see history; screens will use the same answer.
"""

import math
from typing import Protocol

from tyche.core.domain import ScoredInstrument, UniverseMember
from tyche.core.events import Envelope, EventBus, ScreeningEvent, UniverseEvent

SUBSCRIBER = "screening"


class ScreeningError(Exception):
    """A screen produced a score that cannot be ranked. A bug in the screen."""


class Screen(Protocol):
    """Scores an eligible instrument. Higher scores rank first.

    A screen must be deterministic and must not keep state between calls: it is given
    one member at a time and nothing else.
    """

    @property
    def name(self) -> str:
        """A short, stable name, recorded in every ``ScreeningEvent``."""
        ...

    def score(self, member: UniverseMember) -> float:
        """A finite number. Higher ranks first."""
        ...


class DollarVolumeScreen:
    """Ranks by average dollar volume: the most traded instruments first.

    Neutral on purpose. It says nothing about which instrument will do well, only which
    can be traded most easily, and leaves the choosing to the strategies.
    """

    name = "dollar_volume"

    def score(self, member: UniverseMember) -> float:
        return member.average_dollar_volume


class ScreeningStage:
    """Pipeline stage 2. Publishes a ``ScreeningEvent`` for every ``UniverseEvent``.

    Args:
        bus: The run's event bus.
        screen: How to score each eligible instrument.
        limit: Keep only this many of the best-ranked instruments, or ``None`` for all.
            The rest are listed in the event's ``cut``.
    """

    def __init__(self, bus: EventBus, screen: Screen, *, limit: int | None = None) -> None:
        if limit is not None and limit < 1:
            raise ValueError(f"screening limit must be at least 1, got {limit}")
        self._bus = bus
        self._screen = screen
        self._limit = limit
        bus.subscribe(UniverseEvent, self._on_universe, name=SUBSCRIBER)

    def _on_universe(self, envelope: Envelope[UniverseEvent]) -> None:
        universe = envelope.event
        scored: list[ScoredInstrument] = []
        for member in universe.eligible:
            score = self._screen.score(member)
            if not math.isfinite(score):
                raise ScreeningError(
                    f"screen {self._screen.name!r} gave {member.instrument} the score {score}"
                )
            scored.append(ScoredInstrument(member.instrument, score))
        scored.sort(key=lambda s: (-s.score, s.instrument.symbol, s.instrument.exchange))
        kept = scored if self._limit is None else scored[: self._limit]
        cut = tuple(s.instrument for s in scored[len(kept) :])
        self._bus.publish(ScreeningEvent(universe.as_of, self._screen.name, tuple(kept), cut))

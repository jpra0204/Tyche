"""The event bus: synchronous, single-threaded and deterministic (ADR-0003)."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tyche.core.events.event import Envelope, Event

type Handler[E: Event] = Callable[[Envelope[E]], None]

DEFAULT_MAX_EVENTS_PER_DRAIN = 1_000_000


class BusError(Exception):
    """The bus was used in a way it does not allow."""


class BusHaltedError(BusError):
    """The bus stopped after a failure and accepts no more work."""


class HandlerError(BusError):
    """A subscriber raised while handling an event. The bus is now halted.

    The original exception is available as ``__cause__``.
    """

    def __init__(self, subscriber: str, envelope: Envelope[Event]) -> None:
        super().__init__(
            f"subscriber {subscriber!r} failed handling {type(envelope.event).__name__} "
            f"(seq {envelope.seq}); the bus is halted"
        )
        self.subscriber = subscriber
        self.envelope = envelope


class RunawayDispatchError(BusError):
    """One drain handled more events than the configured limit. The bus is now halted.

    This almost always means two handlers are publishing events for each other in a
    loop that never ends.
    """


@dataclass(frozen=True, slots=True)
class _Subscription:
    event_type: type[Event]
    handler: Callable[[Envelope[Any]], None]
    name: str


class EventBus:
    """Delivers events to subscribers, one at a time, in a fixed order.

    The rules, all from ADR-0003:

    * ``publish`` only adds to a FIFO queue. It never calls a handler.
    * ``drain`` handles queued events one by one until the queue is empty, including
      every event published along the way. This is "run to completion": the engine
      feeds one outside input, drains, then feeds the next.
    * For each event, subscribers run in the order they were registered.
    * Subscriptions close at the first ``publish``, so every subscriber sees every
      event from the start of the run.
    * If a handler raises, the bus halts for good. Nothing queued is delivered.

    The bus also fills in the envelope. An event published from inside a handler gets
    ``caused_by``, ``source`` and ``cycle_id`` from the event being handled, so the
    causal chain is recorded without any component having to remember to do it.

    Args:
        now: Returns the current time in UTC. Pass the clock's ``now`` method; in a
            backtest that is simulated time.
        max_events_per_drain: Safety limit on events handled by a single ``drain``.
    """

    def __init__(
        self,
        now: Callable[[], datetime],
        *,
        max_events_per_drain: int = DEFAULT_MAX_EVENTS_PER_DRAIN,
    ) -> None:
        if max_events_per_drain < 1:
            raise ValueError("max_events_per_drain must be at least 1")
        self._now = now
        self._max_events_per_drain = max_events_per_drain
        self._subscriptions: list[_Subscription] = []
        self._matches: dict[type[Event], tuple[_Subscription, ...]] = {}
        self._checked_types: set[type[Event]] = set()
        self._queue: deque[Envelope[Event]] = deque()
        self._next_seq = 1
        self._closed = False
        self._halted = False
        self._handling: Envelope[Event] | None = None
        self._handling_subscriber: str | None = None

    # --- state -------------------------------------------------------------------

    @property
    def pending(self) -> int:
        """Number of published events not yet handled."""
        return len(self._queue)

    @property
    def halted(self) -> bool:
        """True once a failure has stopped the bus."""
        return self._halted

    # --- wiring ------------------------------------------------------------------

    def subscribe[E: Event](self, event_type: type[E], handler: Handler[E], *, name: str) -> None:
        """Register ``handler`` for ``event_type`` and all of its subclasses.

        Subscribing to ``Event`` itself receives everything, which is how the journal
        works. ``name`` identifies the component: it becomes the ``source`` of anything
        the handler publishes and appears in error messages.
        """
        if self._closed:
            raise BusError(
                f"cannot subscribe {name!r}: subscriptions close at the first publish, "
                "so that every subscriber sees the whole run"
            )
        if not name:
            raise ValueError("a subscriber needs a name")
        if not (isinstance(event_type, type) and issubclass(event_type, Event)):
            raise TypeError(f"can only subscribe to Event types, got {event_type!r}")
        self._subscriptions.append(_Subscription(event_type, handler, name))

    # --- publishing --------------------------------------------------------------

    def publish(
        self,
        event: Event,
        *,
        source: str | None = None,
        cycle_id: str | None = None,
    ) -> Envelope[Event]:
        """Queue ``event`` for delivery and return its envelope.

        Called from inside a handler, ``source`` defaults to that subscriber's name and
        ``cycle_id`` to the cycle of the event being handled. Called from outside (an
        input from the feed or the broker), ``source`` is required.
        """
        if self._halted:
            raise BusHaltedError("the bus is halted and accepts no more events")
        self._require_immutable_event(event)

        cause = self._handling
        if source is None:
            source = self._handling_subscriber
        if source is None:
            raise BusError(
                f"{type(event).__name__} was published from outside a handler "
                "without a source; say where it came from"
            )
        if cycle_id is None and cause is not None:
            cycle_id = cause.cycle_id

        envelope = Envelope(
            seq=self._next_seq,
            occurred_at=self._now(),
            source=source,
            event=event,
            caused_by=None if cause is None else cause.seq,
            cycle_id=cycle_id,
        )
        self._next_seq += 1
        self._closed = True
        self._queue.append(envelope)
        return envelope

    # --- dispatch ----------------------------------------------------------------

    def drain(self) -> int:
        """Handle queued events until none are left. Return how many were handled."""
        if self._halted:
            raise BusHaltedError("the bus is halted and will not deliver events")
        if self._handling is not None:
            raise BusError("drain() was called from inside a handler; handlers only publish")

        handled = 0
        while self._queue:
            if handled >= self._max_events_per_drain:
                self._halted = True
                raise RunawayDispatchError(
                    f"more than {self._max_events_per_drain} events in one drain; "
                    "handlers are probably publishing to each other in a loop"
                )
            envelope = self._queue.popleft()
            self._deliver(envelope)
            handled += 1
        return handled

    def _deliver(self, envelope: Envelope[Event]) -> None:
        self._handling = envelope
        try:
            for subscription in self._subscribers_for(type(envelope.event)):
                self._handling_subscriber = subscription.name
                try:
                    subscription.handler(envelope)
                except Exception as error:
                    # Fail closed: a trading system that carries on after an unexpected
                    # error is worse than one that stops.
                    self._halted = True
                    raise HandlerError(subscription.name, envelope) from error
        finally:
            self._handling = None
            self._handling_subscriber = None

    def _subscribers_for(self, event_type: type[Event]) -> tuple[_Subscription, ...]:
        # Safe to cache: subscriptions cannot change once anything has been published.
        matches = self._matches.get(event_type)
        if matches is None:
            matches = tuple(s for s in self._subscriptions if issubclass(event_type, s.event_type))
            self._matches[event_type] = matches
        return matches

    def _require_immutable_event(self, event: Event) -> None:
        event_type = type(event)
        if event_type in self._checked_types:
            return
        candidate: object = event
        if not isinstance(candidate, Event):
            raise TypeError(f"can only publish Event instances, got {event_type.__name__}")
        if event_type is Event:
            raise TypeError("publish a specific event type, not the Event base class")
        params = getattr(event_type, "__dataclass_params__", None)
        if params is None or not params.frozen:
            raise TypeError(
                f"{event_type.__name__} must be a frozen dataclass: events are immutable"
            )
        self._checked_types.add(event_type)

"""The event bus: FIFO, run to completion, fixed handler order, fail closed (ADR-0003)."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from tests.support.recording import START, Recorder, TickingClock
from tyche.core.events import (
    BusError,
    BusHaltedError,
    Envelope,
    Event,
    EventBus,
    HandlerError,
    RunawayDispatchError,
)


@dataclass(frozen=True, slots=True)
class TickEvent(Event):
    n: int


@dataclass(frozen=True, slots=True)
class UrgentTickEvent(TickEvent):
    pass


@dataclass(frozen=True, slots=True)
class EchoEvent(Event):
    of: int
    copy: int


@dataclass(frozen=True, slots=True)
class PingEvent(Event):
    pass


@dataclass(frozen=True, slots=True)
class PongEvent(Event):
    pass


def make_bus(**options: Any) -> EventBus:
    return EventBus(TickingClock().now, **options)


class TestPublish:
    def test_publish_queues_and_does_not_call_handlers(self) -> None:
        bus = make_bus()
        recorder = Recorder(bus)

        bus.publish(TickEvent(1), source="feed")

        assert len(recorder) == 0
        assert bus.pending == 1

    def test_envelope_carries_sequence_time_and_source(self) -> None:
        bus = make_bus()

        first = bus.publish(TickEvent(1), source="feed")
        second = bus.publish(TickEvent(2), source="broker")

        assert (first.seq, first.source, first.occurred_at) == (1, "feed", START)
        assert (second.seq, second.source) == (2, "broker")
        assert second.occurred_at == START + timedelta(seconds=1)
        assert first.event == TickEvent(1)

    def test_an_input_from_outside_has_no_cause_and_no_cycle(self) -> None:
        envelope = make_bus().publish(TickEvent(1), source="feed")

        assert envelope.caused_by is None
        assert envelope.cycle_id is None

    def test_an_input_from_outside_must_name_its_source(self) -> None:
        with pytest.raises(BusError, match="without a source"):
            make_bus().publish(TickEvent(1))

    def test_an_input_can_start_a_cycle(self) -> None:
        envelope = make_bus().publish(TickEvent(1), source="feed", cycle_id="2024-01-02/1d")

        assert envelope.cycle_id == "2024-01-02/1d"


class TestDrain:
    def test_delivers_in_publish_order_and_reports_the_count(self) -> None:
        bus = make_bus()
        recorder = Recorder(bus)
        for n in (1, 2, 3):
            bus.publish(TickEvent(n), source="feed")

        handled = bus.drain()

        assert handled == 3
        assert recorder.events == [TickEvent(1), TickEvent(2), TickEvent(3)]
        assert bus.pending == 0

    def test_draining_an_empty_bus_does_nothing(self) -> None:
        assert make_bus().drain() == 0

    def test_an_event_nobody_subscribed_to_is_still_consumed(self) -> None:
        bus = make_bus()
        bus.publish(TickEvent(1), source="feed")

        assert bus.drain() == 1
        assert bus.pending == 0

    def test_events_published_by_handlers_join_the_back_of_the_queue(self) -> None:
        bus = make_bus()

        def echo_twice(envelope: Envelope[TickEvent]) -> None:
            bus.publish(EchoEvent(of=envelope.event.n, copy=1))
            bus.publish(EchoEvent(of=envelope.event.n, copy=2))

        bus.subscribe(TickEvent, echo_twice, name="echo")
        recorder = Recorder(bus)
        bus.publish(TickEvent(1), source="feed")
        bus.publish(TickEvent(2), source="feed")

        handled = bus.drain()

        # Both ticks are handled before any echo: first in, first out.
        assert recorder.events == [
            TickEvent(1),
            TickEvent(2),
            EchoEvent(of=1, copy=1),
            EchoEvent(of=1, copy=2),
            EchoEvent(of=2, copy=1),
            EchoEvent(of=2, copy=2),
        ]
        assert handled == 6

    def test_sequence_numbers_continue_across_drains(self) -> None:
        bus = make_bus()
        recorder = Recorder(bus)

        bus.publish(TickEvent(1), source="feed")
        bus.drain()
        bus.publish(TickEvent(2), source="feed")
        bus.drain()

        assert [e.seq for e in recorder] == [1, 2]

    def test_draining_between_inputs_applies_consequences_before_the_next_input(self) -> None:
        """Why the engine drains after each input instead of publishing a batch.

        A bar arrives and fills an order; then "data ready" triggers a decision. The
        decision must see the fill. That only holds if the bar's consequences are
        finished before the next input is published.
        """

        def run(*, drain_between_inputs: bool) -> list[str]:
            bus = make_bus()
            log: list[str] = []
            filled = False

            def broker_fills_on_bar(envelope: Envelope[PingEvent]) -> None:
                bus.publish(EchoEvent(of=0, copy=0))  # stands in for a FillEvent

            def account_applies_fill(envelope: Envelope[EchoEvent]) -> None:
                nonlocal filled
                filled = True

            def strategy_decides(envelope: Envelope[PongEvent]) -> None:
                log.append("decided with fill" if filled else "decided WITHOUT fill")

            bus.subscribe(PingEvent, broker_fills_on_bar, name="broker")
            bus.subscribe(EchoEvent, account_applies_fill, name="account")
            bus.subscribe(PongEvent, strategy_decides, name="strategy")

            bus.publish(PingEvent(), source="feed")  # the bar
            if drain_between_inputs:
                bus.drain()
            bus.publish(PongEvent(), source="feed")  # data ready
            bus.drain()
            return log

        assert run(drain_between_inputs=True) == ["decided with fill"]
        assert run(drain_between_inputs=False) == ["decided WITHOUT fill"]


class TestSubscriberOrder:
    def test_subscribers_run_in_registration_order(self) -> None:
        bus = make_bus()
        calls: list[str] = []

        def make(name: str) -> Any:
            return lambda envelope: calls.append(name)

        bus.subscribe(TickEvent, make("first"), name="first")
        bus.subscribe(Event, make("second, subscribed to everything"), name="second")
        bus.subscribe(TickEvent, make("third"), name="third")
        bus.publish(TickEvent(1), source="feed")

        bus.drain()

        assert calls == ["first", "second, subscribed to everything", "third"]

    def test_a_subscription_covers_subclasses_but_not_parents(self) -> None:
        bus = make_bus()
        ticks: list[Event] = []
        urgent: list[Event] = []
        bus.subscribe(TickEvent, lambda e: ticks.append(e.event), name="ticks")
        bus.subscribe(UrgentTickEvent, lambda e: urgent.append(e.event), name="urgent")
        bus.publish(TickEvent(1), source="feed")
        bus.publish(UrgentTickEvent(2), source="feed")

        bus.drain()

        assert ticks == [TickEvent(1), UrgentTickEvent(2)]
        assert urgent == [UrgentTickEvent(2)]

    def test_subscriptions_close_at_the_first_publish(self) -> None:
        bus = make_bus()
        bus.publish(TickEvent(1), source="feed")

        with pytest.raises(BusError, match="subscriptions close at the first publish"):
            bus.subscribe(TickEvent, lambda e: None, name="late")

    def test_a_subscriber_needs_a_name(self) -> None:
        with pytest.raises(ValueError, match="needs a name"):
            make_bus().subscribe(TickEvent, lambda e: None, name="")

    def test_only_event_types_can_be_subscribed_to(self) -> None:
        not_an_event_type: Any = int
        with pytest.raises(TypeError, match="can only subscribe to Event types"):
            make_bus().subscribe(not_an_event_type, lambda e: None, name="x")


class TestCausation:
    def test_events_published_by_a_handler_record_cause_source_and_cycle(self) -> None:
        bus = make_bus()

        def echo(envelope: Envelope[TickEvent]) -> None:
            bus.publish(EchoEvent(of=envelope.event.n, copy=1))

        bus.subscribe(TickEvent, echo, name="echo")
        recorder = Recorder(bus)
        bus.publish(TickEvent(1), source="feed", cycle_id="cycle-A")
        bus.publish(TickEvent(2), source="feed")

        bus.drain()

        assert recorder.trace == [
            (1, "TickEvent", "feed", None, "cycle-A"),
            (2, "TickEvent", "feed", None, None),
            (3, "EchoEvent", "echo", 1, "cycle-A"),
            (4, "EchoEvent", "echo", 2, None),
        ]

    def test_the_chain_can_be_followed_back_to_the_input(self) -> None:
        bus = make_bus()

        def ping_to_pong(envelope: Envelope[PingEvent]) -> None:
            bus.publish(PongEvent())

        def pong_to_echo(envelope: Envelope[PongEvent]) -> None:
            bus.publish(EchoEvent(of=0, copy=0))

        bus.subscribe(PingEvent, ping_to_pong, name="a")
        bus.subscribe(PongEvent, pong_to_echo, name="b")
        recorder = Recorder(bus)
        bus.publish(PingEvent(), source="feed")
        bus.drain()

        by_seq = {e.seq: e for e in recorder}
        chain = []
        current: Envelope[Event] | None = recorder.envelopes[-1]
        while current is not None:
            chain.append(type(current.event).__name__)
            current = by_seq[current.caused_by] if current.caused_by is not None else None

        assert chain == ["EchoEvent", "PongEvent", "PingEvent"]

    def test_a_handler_can_start_a_new_cycle_or_name_another_source(self) -> None:
        bus = make_bus()

        def relabel(envelope: Envelope[TickEvent]) -> None:
            bus.publish(PongEvent(), source="scheduler", cycle_id="cycle-B")

        bus.subscribe(TickEvent, relabel, name="relabel")
        recorder = Recorder(bus)
        bus.publish(TickEvent(1), source="feed", cycle_id="cycle-A")

        bus.drain()

        assert recorder.trace[-1] == (2, "PongEvent", "scheduler", 1, "cycle-B")

    def test_the_cause_is_cleared_once_handling_ends(self) -> None:
        bus = make_bus()
        bus.subscribe(TickEvent, lambda e: None, name="noop")
        bus.publish(TickEvent(1), source="feed", cycle_id="cycle-A")
        bus.drain()

        later = bus.publish(TickEvent(2), source="feed")

        assert later.caused_by is None
        assert later.cycle_id is None


class TestFailClosed:
    def make_failing_bus(self) -> tuple[EventBus, list[str]]:
        bus = make_bus()
        calls: list[str] = []

        def publish_then_fail(envelope: Envelope[TickEvent]) -> None:
            calls.append("failing")
            bus.publish(EchoEvent(of=envelope.event.n, copy=1))
            raise RuntimeError("boom")

        bus.subscribe(TickEvent, publish_then_fail, name="failing")
        bus.subscribe(TickEvent, lambda e: calls.append("after"), name="after")
        bus.subscribe(EchoEvent, lambda e: calls.append("echo"), name="echo")
        bus.publish(TickEvent(1), source="feed")
        bus.publish(TickEvent(2), source="feed")
        return bus, calls

    def test_a_failing_handler_raises_handler_error_with_the_details(self) -> None:
        bus, _ = self.make_failing_bus()

        with pytest.raises(HandlerError, match=r"'failing' failed handling TickEvent") as caught:
            bus.drain()

        assert caught.value.subscriber == "failing"
        assert caught.value.envelope.seq == 1
        assert isinstance(caught.value.__cause__, RuntimeError)

    def test_nothing_else_is_delivered_after_a_failure(self) -> None:
        bus, calls = self.make_failing_bus()

        with pytest.raises(HandlerError):
            bus.drain()

        # Not the next subscriber, not the next tick, not the event the handler queued.
        assert calls == ["failing"]
        assert bus.pending == 2

    def test_a_halted_bus_refuses_all_further_work(self) -> None:
        bus, _ = self.make_failing_bus()
        with pytest.raises(HandlerError):
            bus.drain()

        assert bus.halted
        with pytest.raises(BusHaltedError):
            bus.publish(TickEvent(3), source="feed")
        with pytest.raises(BusHaltedError):
            bus.drain()

    def test_a_healthy_bus_is_not_halted(self) -> None:
        bus = make_bus()
        bus.publish(TickEvent(1), source="feed")
        bus.drain()

        assert not bus.halted

    def test_a_handler_may_not_drain(self) -> None:
        bus = make_bus()

        def drain_again(envelope: Envelope[TickEvent]) -> None:
            bus.drain()

        bus.subscribe(TickEvent, drain_again, name="nested")
        bus.publish(TickEvent(1), source="feed")

        with pytest.raises(HandlerError) as caught:
            bus.drain()

        assert isinstance(caught.value.__cause__, BusError)
        assert "inside a handler" in str(caught.value.__cause__)

    def test_an_endless_loop_between_handlers_is_stopped(self) -> None:
        bus = make_bus(max_events_per_drain=50)

        def ping(envelope: Envelope[PingEvent]) -> None:
            bus.publish(PongEvent())

        def pong(envelope: Envelope[PongEvent]) -> None:
            bus.publish(PingEvent())

        bus.subscribe(PingEvent, ping, name="ping")
        bus.subscribe(PongEvent, pong, name="pong")
        bus.publish(PingEvent(), source="feed")

        with pytest.raises(RunawayDispatchError, match="more than 50 events"):
            bus.drain()

        assert bus.halted

    def test_the_drain_limit_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            make_bus(max_events_per_drain=0)


class TestOnlyImmutableEvents:
    def test_a_mutable_dataclass_is_rejected(self) -> None:
        @dataclass
        class MutableEvent(Event):
            n: int

        with pytest.raises(TypeError, match="MutableEvent must be a frozen dataclass"):
            make_bus().publish(MutableEvent(1), source="feed")

    def test_a_plain_class_is_rejected(self) -> None:
        class PlainEvent(Event):
            pass

        with pytest.raises(TypeError, match="PlainEvent must be a frozen dataclass"):
            make_bus().publish(PlainEvent(), source="feed")

    def test_the_bare_base_class_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="publish a specific event type"):
            make_bus().publish(Event(), source="feed")

    def test_something_that_is_not_an_event_is_rejected(self) -> None:
        not_an_event: Any = "tick"
        with pytest.raises(TypeError, match="can only publish Event instances"):
            make_bus().publish(not_an_event, source="feed")

    def test_a_rejected_publish_leaves_the_bus_open_for_subscriptions(self) -> None:
        bus = make_bus()
        with pytest.raises(BusError):
            bus.publish(TickEvent(1))  # no source

        recorder = Recorder(bus)
        bus.publish(TickEvent(1), source="feed")
        bus.drain()

        assert recorder.events == [TickEvent(1)]


def test_the_same_inputs_always_produce_the_same_sequence() -> None:
    def run() -> list[Envelope[Event]]:
        bus = make_bus()

        def fan_out(envelope: Envelope[TickEvent]) -> None:
            for copy in range(envelope.event.n):
                bus.publish(EchoEvent(of=envelope.event.n, copy=copy))

        def react(envelope: Envelope[EchoEvent]) -> None:
            if envelope.event.copy == 0:
                bus.publish(PongEvent())

        bus.subscribe(TickEvent, fan_out, name="fan_out")
        bus.subscribe(EchoEvent, react, name="react")
        recorder = Recorder(bus)
        for n in (3, 1, 2):
            bus.publish(TickEvent(n), source="feed", cycle_id=f"cycle-{n}")
            bus.drain()
        return recorder.envelopes

    first, second = run(), run()

    assert len(first) == 12
    assert first == second  # every field of every envelope, timestamps included

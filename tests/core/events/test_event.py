"""Event naming and the envelope's own rules."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from tyche.core.events import Envelope, Event


@dataclass(frozen=True, slots=True)
class SampleEvent(Event):
    value: int


NOON = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)


def test_an_event_class_must_be_named_something_event() -> None:
    with pytest.raises(TypeError, match="'Fill' must have a name ending in 'Event'"):

        class Fill(Event):
            pass


def test_events_compare_by_value() -> None:
    assert SampleEvent(1) == SampleEvent(1)
    assert SampleEvent(1) != SampleEvent(2)


def test_an_event_is_immutable() -> None:
    event: Any = SampleEvent(1)
    with pytest.raises(FrozenInstanceError):
        event.value = 2


def test_envelope_defaults_to_no_cause_and_no_cycle() -> None:
    envelope = Envelope(seq=1, occurred_at=NOON, source="feed", event=SampleEvent(1))

    assert envelope.caused_by is None
    assert envelope.cycle_id is None


def test_an_envelope_is_immutable() -> None:
    envelope: Any = Envelope(seq=1, occurred_at=NOON, source="feed", event=SampleEvent(1))
    with pytest.raises(FrozenInstanceError):
        envelope.seq = 2


def test_envelope_rejects_a_naive_time() -> None:
    naive = datetime(2024, 1, 2, 12, 0)  # noqa: DTZ001 - the mistake under test
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Envelope(seq=1, occurred_at=naive, source="feed", event=SampleEvent(1))


def test_envelope_rejects_a_local_time() -> None:
    local = datetime(2024, 1, 2, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Envelope(seq=1, occurred_at=local, source="feed", event=SampleEvent(1))

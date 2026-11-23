"""The event codec: what it writes reads back equal, and it refuses anything it could not."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import tyche.core.events
from tests.support.events import rare_events
from tyche.adapters.storage import codec
from tyche.adapters.storage.codec import CodecError
from tyche.core.domain import Account, Currency, Money
from tyche.core.events import CancelRequestEvent, Event


@dataclass(frozen=True, slots=True)
class HomemadeEvent(Event):
    n: int


@pytest.mark.parametrize("event", rare_events(), ids=lambda e: type(e).__name__)
def test_rare_events_read_back_equal(event: Event) -> None:
    back = codec.loads(codec.dumps(event))

    assert back == event
    assert type(back) is type(event)


def test_an_account_with_object_keys_reads_back_equal() -> None:
    account = Account.empty().deposit(Money(Decimal("10000.00"), Currency.USD))

    raw = codec.encode(account)

    assert codec.decode(json.loads(json.dumps(raw))) == account


def test_every_exported_event_type_can_be_stored() -> None:
    exported = {
        getattr(tyche.core.events, name)
        for name in tyche.core.events.__all__
        if isinstance(getattr(tyche.core.events, name), type)
    }
    events = {t for t in exported if issubclass(t, Event) and t is not Event}

    assert events <= set(codec.stored_types().values())


scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.decimals(allow_nan=False, allow_infinity=False),
    st.dates(),
    st.datetimes(timezones=st.just(UTC)),
    st.sampled_from(list(Currency)),
)
hashable = st.recursive(scalars, lambda inner: st.tuples(inner, inner), max_leaves=6)
values = st.recursive(
    scalars,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4).map(tuple),
        st.lists(inner, max_size=4),
        st.frozensets(hashable, max_size=4),
        st.dictionaries(hashable, inner, max_size=4),
    ),
    max_leaves=12,
)


@given(values)
def test_any_supported_value_reads_back_equal_and_of_the_same_type(value: Any) -> None:
    back = codec.decode(json.loads(json.dumps(codec.encode(value), allow_nan=False)))

    assert back == value
    assert _shape(back) == _shape(value)


def _shape(value: Any) -> Any:
    """The types inside a value, so that 1 and 1.0, or a tuple and a list, differ."""
    if isinstance(value, tuple | list):
        return (type(value), [_shape(v) for v in value])
    if isinstance(value, dict):
        return (dict, sorted(repr(_shape(k)) + repr(_shape(v)) for k, v in value.items()))
    if isinstance(value, frozenset):
        return (frozenset, sorted(repr(_shape(v)) for v in value))
    return type(value)


def test_a_decimal_keeps_its_exact_digits() -> None:
    back = codec.decode(codec.encode(Decimal("1.50")))

    assert str(back) == "1.50"


def test_a_datetime_keeps_its_offset_and_a_naive_one_is_refused() -> None:
    moment = datetime(2024, 1, 2, 21, 0, tzinfo=timezone(timedelta(hours=-5)))

    assert codec.decode(codec.encode(moment)).utcoffset() == timedelta(hours=-5)
    with pytest.raises(CodecError, match="naive"):
        codec.encode(datetime(2024, 1, 2, 21, 0))  # noqa: DTZ001 (the point of the test)


def test_refuses_to_store_a_type_tyche_does_not_export() -> None:
    with pytest.raises(CodecError, match="not exported"):
        codec.dumps(HomemadeEvent(1))


def test_refuses_to_store_something_that_is_not_an_event() -> None:
    with pytest.raises(CodecError, match="only events"):
        codec.dumps(Money(Decimal(1), Currency.USD))  # type: ignore[arg-type]


def test_refuses_a_value_it_has_no_rule_for() -> None:
    with pytest.raises(CodecError, match="cannot store a set"):
        codec.encode({1, 2})


@pytest.mark.parametrize(
    ("stored", "message"),
    [
        ('{"$type":"Path","fields":{}}', "not a type the journal stores"),
        (
            '{"$type":"CancelRequestEvent","fields":{"client_order_id":"a","reason":"b",'
            '"extra":1}}',
            "does not know",
        ),
        (
            '{"$type":"CancelRequestEvent","fields":{"client_order_id":"a","reason":" "}}',
            "cannot be rebuilt",
        ),
        ('{"$enum":"Currency","name":"XXX"}', "no member"),
        ('{"$enum":"CancelRequestEvent","name":"A"}', "not an enum"),
        ('{"$decimal":"abc"}', "cannot be read"),
        ('{"$datetime":"2024-01-02T21:00:00"}', "no timezone"),
        ('{"$map":[[1]]}', "list of pairs"),
        ('{"$what":1}', "unknown tag"),
        ('{"a":1,"b":2}', "unexpected stored object"),
        (
            '{"$type":"Money","fields":{"amount":{"$decimal":"1"},"currency":'
            '{"$enum":"Currency","name":"USD"}}}',
            "not an event",
        ),
        ("{not json", "not valid JSON"),
    ],
)
def test_refuses_stored_text_it_cannot_read_back_exactly(stored: str, message: str) -> None:
    with pytest.raises(CodecError, match=message):
        codec.loads(stored)


def test_reads_what_it_wrote_for_a_simple_event() -> None:
    event = CancelRequestEvent("o-1", "replaced by a new stop")

    text = codec.dumps(event)

    assert json.loads(text) == {
        "$type": "CancelRequestEvent",
        "fields": {"client_order_id": "o-1", "reason": "replaced by a new stop"},
    }
    assert codec.loads(text) == event


def test_dates_and_datetimes_are_kept_apart() -> None:
    assert type(codec.decode(codec.encode(date(2024, 1, 2)))) is date
    assert type(codec.decode(codec.encode(datetime(2024, 1, 2, tzinfo=UTC)))) is datetime

"""The event codec: Tyche's events as JSON text, and back to the same objects (ADR-0037).

Every value an event can hold is written so that reading it gives back an equal
object of the same type. JSON's own values (strings, whole numbers, floats, true,
false, null, lists) stand for themselves. Everything else is an object with one tag:

=================  ==============================================================
``$type``          a dataclass by its class name, with its constructor ``fields``
``$enum``          an enum member: the class name and the member's ``name``
``$decimal``       a ``Decimal`` as its exact text
``$datetime``      a timezone-aware datetime in ISO 8601
``$date``          a date in ISO 8601
``$tuple``         a tuple, as a list
``$frozenset``     a frozenset, as a list in a fixed order
``$map``           a mapping, as a list of key and value pairs (keys may be objects)
=================  ==============================================================

Only the dataclasses and enums exported by ``tyche.core.domain`` and
``tyche.core.events`` can be written or read, by name. Anything else is refused when it
is written, so the journal never holds a value it could not read back, and a stored
name never makes the reader import or build anything else.

Checkpoints (ADR-0038) are written the same way, through ``dumps_checkpoint`` and
``loads_checkpoint``: every part of one is a value object of ``tyche.core.domain``.

``FORMAT`` is stored with every row. Change it only with a reader for the old format:
rows are never rewritten (ADR-0009).
"""

import dataclasses
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import cache
from typing import Any

import tyche.core.domain
import tyche.core.events
from tyche.core.domain import Checkpoint
from tyche.core.events import Event

FORMAT = 1
"""The version of the encoding below. Stored with every journal row."""


class CodecError(ValueError):
    """A value cannot be written as JSON, or stored JSON cannot be read back."""


@cache
def stored_types() -> Mapping[str, type]:
    """Every class the codec writes and reads, by name.

    The dataclasses and enums in ``tyche.core.domain.__all__`` and
    ``tyche.core.events.__all__``. Two classes with one name would make a stored name
    ambiguous, so that is refused.
    """
    found: dict[str, type] = {}
    for module in (tyche.core.domain, tyche.core.events):
        for name in module.__all__:
            candidate = getattr(module, name)
            if not isinstance(candidate, type):
                continue
            if not (dataclasses.is_dataclass(candidate) or issubclass(candidate, Enum)):
                continue
            key = candidate.__name__
            if found.get(key, candidate) is not candidate:
                raise CodecError(f"two stored types are named {key!r}")
            found[key] = candidate
    return found


def dumps(event: Event) -> str:
    """``event`` as compact JSON text. Raises ``CodecError`` if any part cannot be stored."""
    if not isinstance(event, Event):
        raise CodecError(f"only events are stored, not {type(event).__name__}")
    return _dumps(event)


def loads(text: str) -> Event:
    """The event that ``dumps`` wrote as ``text``."""
    event = _loads(text, "event")
    if not isinstance(event, Event):
        raise CodecError(f"stored value is a {type(event).__name__}, not an event")
    return event


def dumps_checkpoint(checkpoint: Checkpoint) -> str:
    """``checkpoint`` as compact JSON text, in the same encoding as events (ADR-0038)."""
    if not isinstance(checkpoint, Checkpoint):
        raise CodecError(f"expected a Checkpoint, not {type(checkpoint).__name__}")
    return _dumps(checkpoint)


def loads_checkpoint(text: str) -> Checkpoint:
    """The checkpoint that ``dumps_checkpoint`` wrote as ``text``.

    Rebuilding it runs its checks again: a stored checkpoint whose parts disagree is
    refused, not loaded.
    """
    checkpoint = _loads(text, "checkpoint")
    if not isinstance(checkpoint, Checkpoint):
        raise CodecError(f"stored value is a {type(checkpoint).__name__}, not a checkpoint")
    return checkpoint


def _dumps(value: object) -> str:
    try:
        # ensure_ascii: a stray lone surrogate in a string is escaped, not a broken row.
        return json.dumps(encode(value), allow_nan=False, separators=(",", ":"))
    except ValueError as error:  # a NaN or an infinite float
        raise CodecError(f"{type(value).__name__} cannot be stored: {error}") from error


def _loads(text: str, what: str) -> Any:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise CodecError(f"stored {what} is not valid JSON: {error}") from error
    return decode(raw)


def encode(value: object) -> Any:
    """``value`` as plain JSON values, tagged as the module docstring describes."""
    # Enums first: a StrEnum is also a str, and an IntEnum an int.
    if isinstance(value, Enum):
        _require_stored(type(value))
        return {"$enum": type(value).__name__, "name": value.name}
    if value is None or isinstance(value, bool | int | str | float):
        return value
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    # datetime before date: a datetime is also a date.
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise CodecError(f"cannot store a naive datetime: {value!r}")
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, tuple):
        return {"$tuple": [encode(item) for item in value]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, frozenset):
        items = [encode(item) for item in value]
        return {"$frozenset": sorted(items, key=_sort_key)}
    if isinstance(value, Mapping):
        return {"$map": [[encode(k), encode(v)] for k, v in value.items()]}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        _require_stored(type(value))
        fields = {
            f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value) if f.init
        }
        return {"$type": type(value).__name__, "fields": fields}
    raise CodecError(f"cannot store a {type(value).__name__}: {value!r}")


def decode(raw: Any) -> Any:
    """The value that ``encode`` turned into ``raw``."""
    if raw is None or isinstance(raw, bool | int | str | float):
        return raw
    if isinstance(raw, list):
        return [decode(item) for item in raw]
    if not isinstance(raw, dict):
        raise CodecError(f"unexpected stored value {raw!r}")
    if "$type" in raw:
        return _decode_dataclass(raw)
    if len(raw) == 2 and "$enum" in raw and "name" in raw:
        cls = _stored_type(raw["$enum"])
        if not issubclass(cls, Enum):
            raise CodecError(f"{raw['$enum']!r} is not an enum")
        try:
            return cls[raw["name"]]
        except KeyError:
            raise CodecError(f"{cls.__name__} has no member {raw['name']!r}") from None
    if len(raw) != 1:
        raise CodecError(f"unexpected stored object with keys {sorted(raw)}")
    ((tag, body),) = raw.items()
    try:
        match tag:
            case "$decimal":
                return Decimal(_text(body, tag))
            case "$datetime":
                moment = datetime.fromisoformat(_text(body, tag))
                if moment.utcoffset() is None:
                    raise CodecError(f"stored datetime {body!r} has no timezone")
                return moment
            case "$date":
                return date.fromisoformat(_text(body, tag))
            case "$tuple":
                return tuple(decode(item) for item in _items(body, tag))
            case "$frozenset":
                return frozenset(decode(item) for item in _items(body, tag))
            case "$map":
                pairs = _items(body, tag)
                if not all(isinstance(pair, list) and len(pair) == 2 for pair in pairs):
                    raise CodecError(f"stored map {body!r} is not a list of pairs")
                return {decode(k): decode(v) for k, v in pairs}
            case _:
                raise CodecError(f"unknown tag {tag!r}")
    except (ArithmeticError, ValueError) as error:
        if isinstance(error, CodecError):
            raise
        raise CodecError(f"stored {tag} {body!r} cannot be read: {error}") from error


def _decode_dataclass(raw: dict[str, Any]) -> Any:
    if set(raw) != {"$type", "fields"} or not isinstance(raw["fields"], dict):
        raise CodecError(f"stored dataclass {raw.get('$type')!r} is malformed")
    cls = _stored_type(raw["$type"])
    if not dataclasses.is_dataclass(cls):
        raise CodecError(f"{raw['$type']!r} is not a dataclass")
    accepted = {f.name for f in dataclasses.fields(cls) if f.init}
    unknown = set(raw["fields"]) - accepted
    if unknown:
        raise CodecError(
            f"stored {cls.__name__} has fields this version does not know: {sorted(unknown)}"
        )
    arguments = {name: decode(value) for name, value in raw["fields"].items()}
    try:
        return cls(**arguments)
    except (TypeError, ValueError) as error:
        raise CodecError(f"stored {cls.__name__} cannot be rebuilt: {error}") from error


def _stored_type(name: object) -> type:
    if not isinstance(name, str) or name not in stored_types():
        raise CodecError(f"{name!r} is not a type the journal stores")
    return stored_types()[name]


def _require_stored(cls: type) -> None:
    if stored_types().get(cls.__name__) is not cls:
        raise CodecError(
            f"{cls.__module__}.{cls.__name__} is not exported by tyche.core.domain or "
            "tyche.core.events, so the journal cannot store it"
        )


def _text(body: object, tag: str) -> str:
    if not isinstance(body, str):
        raise CodecError(f"stored {tag} must be text, got {body!r}")
    return body


def _items(body: object, tag: str) -> list[Any]:
    if not isinstance(body, list):
        raise CodecError(f"stored {tag} must be a list, got {body!r}")
    return body


def _sort_key(encoded: object) -> str:
    return json.dumps(encoded, sort_keys=True, allow_nan=False)

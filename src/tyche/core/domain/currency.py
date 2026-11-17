"""Currencies Tyche can hold cash in."""

from enum import StrEnum


class Currency(StrEnum):
    """An ISO 4217 currency code.

    An enum, not a free string, so that a typo such as ``"UDS"`` is an error at the
    point where it is written. Supporting a new currency means adding one member here.
    """

    CAD = "CAD"
    USD = "USD"

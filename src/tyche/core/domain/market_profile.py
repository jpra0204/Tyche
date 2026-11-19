"""MarketProfile: which markets and which cash a run trades with."""

import re
from dataclasses import dataclass

from tyche.core.domain.currency import Currency
from tyche.core.domain.execution import ExecutionRules
from tyche.core.domain.universe import UniverseRules
from tyche.core.domain.validation import require_mic

# One or more upper-case market names joined by "+", e.g. "US", "CA", "CA+US".
_PROFILE_NAME = re.compile(r"[A-Z]+(?:\+[A-Z]+)*")


def require_profile_name(name: str) -> None:
    """Raise ``ValueError`` unless ``name`` is a valid market profile name.

    Also used before a profile name becomes part of a file path, so that a name such
    as ``../secrets`` can never reach the file system.
    """
    if not _PROFILE_NAME.fullmatch(name):
        raise ValueError(
            f"invalid market profile name {name!r}: expected upper-case names "
            "joined by '+', such as 'US' or 'CA+US'"
        )


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """A named set of markets that compete for the same capital.

    Selecting a profile is how a run says "US only", "Canada only" or "both". Every
    strategy can be backtested under each profile, so their results can be compared.

    Phase 1 builds only ``US``. The benchmark and the currency conversion policy are
    added to the profile in the PRs that first use them.

    Attributes:
        name: Upper-case name, e.g. ``US`` or ``CA+US``.
        cash_currencies: Currencies the account holds cash in for this profile, in a
            fixed order. ``US`` holds only USD; ``CA`` only CAD.
        calendars: MICs of the trading calendars of the profile's markets, e.g.
            ``("XNYS",)``. Every instrument traded under the profile must follow one.
        universe: What an instrument must look like to be eligible. Its thresholds are
            in one of the cash currencies, and only instruments quoted in that currency
            are eligible; a profile with two currencies needs thresholds per currency,
            which comes with the ``CA+US`` profile in Phase 4.
        execution: How approved weights become orders: the rebalance band (ADR-0023).
    """

    name: str
    cash_currencies: tuple[Currency, ...]
    calendars: tuple[str, ...]
    universe: UniverseRules
    execution: ExecutionRules

    def __post_init__(self) -> None:
        require_profile_name(self.name)
        if not self.cash_currencies:
            raise ValueError(f"market profile {self.name}: needs at least one cash currency")
        if len(set(self.cash_currencies)) != len(self.cash_currencies):
            raise ValueError(f"market profile {self.name}: cash currencies are repeated")
        if not self.calendars:
            raise ValueError(f"market profile {self.name}: needs at least one calendar")
        for calendar in self.calendars:
            require_mic(calendar, f"calendar in market profile {self.name}:")
        if len(set(self.calendars)) != len(self.calendars):
            raise ValueError(f"market profile {self.name}: calendars are repeated")
        if self.universe.currency not in self.cash_currencies:
            raise ValueError(
                f"market profile {self.name}: universe thresholds are in "
                f"{self.universe.currency}, which is not one of its cash currencies"
            )

    def __str__(self) -> str:
        return self.name

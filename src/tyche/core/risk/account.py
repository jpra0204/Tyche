"""The account rules: the daily loss limit and the drawdown kill (ADR-0015, ADR-0035).

Both are measured on the account's equity at every session close, from the
``AccountEvent`` the account state publishes before that close's decision:

* **Daily loss limit.** If equity fell by at least ``daily_loss_limit`` since the
  previous close, the decision at this close opens no position and adds to none.
  Exits and reductions still go through, and the next close starts fresh.
* **Drawdown kill.** If equity is at least ``drawdown_kill`` below the highest close
  so far, trading halts. The halt is a latch: once set, nothing in a run clears it.
  Only a manual restart does, which arrives with the kill switch (Phase 2, PR 8).

Equity is the whole account's: cash, settled or not, plus positions at their latest
close, after every fee. Each cash currency is measured on its own until currency
conversion exists (Phase 4), as the money caps are (ADR-0032). Deposits and
withdrawals are not gains or losses; nothing in a backtest makes one after the start,
and paper accounts for them when it reads the broker's cash (Phase 2, PR 13).

``AccountRules`` holds the state (the previous close, the peak, the halt) and decides;
the risk gate publishes what it finds and applies it.
"""

from datetime import datetime
from decimal import Decimal

from tyche.core.domain import Account, AccountTrigger, Currency, Money, RiskRule
from tyche.core.risk.limits import RiskProfile

_SHOWN = Decimal("0.0001")


class AccountRules:
    """The previous close, the peak and the halt, updated close by close. No bus.

    Args:
        profile: The active risk profile, whose two account limits apply.
    """

    def __init__(self, profile: RiskProfile) -> None:
        self._profile = profile
        self._previous: dict[Currency, Money] = {}
        self._peak: dict[Currency, Money] = {}
        self._latest: datetime | None = None
        self._daily_loss: AccountTrigger | None = None
        self._halt: AccountTrigger | None = None

    @property
    def halt(self) -> AccountTrigger | None:
        """The drawdown kill that halted trading, or ``None``. Never cleared in a run."""
        return self._halt

    def peak(self, currency: Currency) -> Money | None:
        """The highest close of equity in ``currency`` so far, or ``None`` before any."""
        return self._peak.get(currency)

    def daily_loss(self, at: datetime) -> AccountTrigger | None:
        """The daily loss limit's trigger at the close ``at``, or ``None``."""
        if self._latest != at:
            return None
        return self._daily_loss

    def close(self, at: datetime, account: Account) -> tuple[AccountTrigger, ...]:
        """Measure the account at one session close, and return what triggered there.

        Raises:
            ValueError: ``at`` is not after the previous close.
        """
        if self._latest is not None and at <= self._latest:
            raise ValueError(
                f"account rules: the close at {at.isoformat()} is not after the previous "
                f"one, {self._latest.isoformat()}"
            )
        self._latest = at
        self._daily_loss = None
        if self._halt is not None:
            return ()
        triggers: list[AccountTrigger] = []
        for currency in account.currencies:
            equity = account.equity(currency)
            previous = self._previous.get(currency)
            self._previous[currency] = equity
            peak = self._peak.get(currency)
            if peak is None or equity > peak:
                peak = self._peak[currency] = equity
            if self._daily_loss is None and previous is not None:
                self._daily_loss = self._daily(at, previous, equity)
                if self._daily_loss is not None:
                    triggers.append(self._daily_loss)
            if self._halt is None:
                self._halt = self._drawdown(at, peak, equity)
                if self._halt is not None:
                    triggers.append(self._halt)
        return tuple(triggers)

    def _daily(self, at: datetime, previous: Money, equity: Money) -> AccountTrigger | None:
        limit = self._profile.daily_loss_limit
        if not previous.is_positive or _fall(previous, equity) < limit:
            return None
        return AccountTrigger(
            RiskRule.DAILY_LOSS_LIMIT,
            at,
            previous,
            equity,
            limit,
            f"equity fell from {previous} at the previous close to {equity}, a loss of "
            f"{_shown(_fall(previous, equity))}, at or above the daily loss limit {limit}: "
            "no entries or additions at this close",
        )

    def _drawdown(self, at: datetime, peak: Money, equity: Money) -> AccountTrigger | None:
        limit = self._profile.drawdown_kill
        if not peak.is_positive or _fall(peak, equity) < limit:
            return None
        return AccountTrigger(
            RiskRule.DRAWDOWN_KILL,
            at,
            peak,
            equity,
            limit,
            f"equity of {equity} is {_shown(_fall(peak, equity))} below its peak of {peak}, "
            f"at or above the drawdown kill {limit}: trading halts until a manual restart",
        )


def _fall(reference: Money, equity: Money) -> Decimal:
    return (reference.amount - equity.amount) / reference.amount


def _shown(fraction: Decimal) -> Decimal:
    return fraction.quantize(_SHOWN)

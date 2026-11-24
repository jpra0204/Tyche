"""The checkpoint: what a run leaves for the next one to carry on from (ADR-0038).

Most of Tyche's state is rebuilt at every start: the universe and the signals windows
are warmed up from cached history (ADR-0021, ADR-0024). The rest cannot be, because it
is the record of what Tyche did, not of what the market did:

* Tyche's own view of the account (the ledger, ``Account``);
* the sleeve book: each strategy's shares, their cost and entry date, and the stop
  resting for them (ADR-0022, ADR-0023);
* execution's working orders, with the shares each still owes to each sleeve, the
  stop each sleeve wants once a purchase fills, and the last decision handled;
* the account rules: the previous close, the peak and the drawdown halt (ADR-0035);
* reconciliation's memory: the last check, and any halt it left (ADR-0044).

A ``Checkpoint`` holds all five, as they were when a run ended. Each part is a value
object, so the state database can store it with the journal's codec (ADR-0037), and it
checks on construction that the parts agree with each other: a checkpoint that does not
add up is refused, never loaded.
"""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal

from tyche.core.domain.account import Account
from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.order import OrderState, OrderType
from tyche.core.domain.reconciliation import ReconciliationState
from tyche.core.domain.risk import AccountTrigger, RiskRule
from tyche.core.domain.signals import require_strategy_id


def _require_aware(moment: datetime, what: str) -> None:
    if moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got {moment!r}")


def _require_shares(quantity: Decimal, what: str) -> None:
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(f"{what}: quantity must be positive, got {quantity}")


def _label(strategy_id: str, instrument: Instrument) -> str:
    return f"{strategy_id} in {instrument}"


@dataclass(frozen=True, slots=True)
class SleeveHolding:
    """One sleeve's shares of one instrument.

    Attributes:
        strategy_id: The sleeve.
        instrument: What it holds.
        quantity: How many shares. Always positive.
        cost: What they cost at their fill or crossing prices, commissions excluded.
        entry_date: The day of the first of these shares.
    """

    strategy_id: str
    instrument: Instrument
    quantity: Decimal
    cost: Money
    entry_date: date

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        what = _label(self.strategy_id, self.instrument)
        _require_shares(self.quantity, what)
        if self.cost.currency is not self.instrument.currency or not self.cost.is_positive:
            raise ValueError(f"{what}: cost must be positive, in its currency; got {self.cost}")


@dataclass(frozen=True, slots=True)
class SleeveStop:
    """The protective stop resting at the broker for one sleeve's shares.

    Attributes:
        strategy_id: The sleeve.
        instrument: The shares it protects.
        client_order_id: The stop order.
        price: Its stop price.
    """

    strategy_id: str
    instrument: Instrument
    client_order_id: str
    price: Money

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        if self.price.currency is not self.instrument.currency or not self.price.is_positive:
            raise ValueError(
                f"stop for {_label(self.strategy_id, self.instrument)}: price must be "
                f"positive, in its currency; got {self.price}"
            )


@dataclass(frozen=True, slots=True)
class SleeveState:
    """The sleeve book: every sleeve's holdings and resting stops.

    Attributes:
        holdings: One entry per sleeve and instrument held.
        stops: One entry per sleeve and instrument with a resting stop.
    """

    holdings: tuple[SleeveHolding, ...] = ()
    stops: tuple[SleeveStop, ...] = ()

    def __post_init__(self) -> None:
        _require_unique(
            ((h.strategy_id, h.instrument) for h in self.holdings), "holding of a sleeve"
        )
        _require_unique(((s.strategy_id, s.instrument) for s in self.stops), "stop of a sleeve")

    def total(self, instrument: Instrument) -> Decimal:
        """Shares of ``instrument`` held across every sleeve."""
        return sum(
            (h.quantity for h in self.holdings if h.instrument == instrument), start=Decimal(0)
        )


@dataclass(frozen=True, slots=True)
class OwedShares:
    """Shares a netted market order still owes one sleeve.

    Attributes:
        strategy_id: The sleeve.
        quantity: Shares still to fill for it. Always positive.
    """

    strategy_id: str
    quantity: Decimal

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        _require_shares(self.quantity, f"shares owed to {self.strategy_id}")


@dataclass(frozen=True, slots=True)
class WorkingOrder:
    """An order execution sent that had not finished when the run ended.

    A market order serves one or more sleeves (``owed``); a stop protects one sleeve's
    shares (``strategy_id``). One or the other, never both.

    Attributes:
        state: The order and where it was.
        owed: For a market order, what it still owes each sleeve; together, its
            remaining shares.
        strategy_id: For a stop, the sleeve it protects.
    """

    state: OrderState
    owed: tuple[OwedShares, ...] = ()
    strategy_id: str | None = None

    def __post_init__(self) -> None:
        order = self.state.order
        what = f"working order {order.client_order_id}"
        if self.state.status.is_terminal:
            raise ValueError(f"{what} has finished ({self.state.status}); it is not working")
        if order.order_type is OrderType.STOP:
            if self.strategy_id is None or self.owed:
                raise ValueError(f"{what} is a stop: it protects one sleeve and owes nothing")
            require_strategy_id(self.strategy_id)
            return
        if self.strategy_id is not None or not self.owed:
            raise ValueError(f"{what} is a market order: it owes shares to one or more sleeves")
        _require_unique(((o.strategy_id,) for o in self.owed), f"sleeve owed by {what}")
        owed = sum((o.quantity for o in self.owed), start=Decimal(0))
        if owed != self.state.remaining:
            raise ValueError(
                f"{what} owes its sleeves {owed} shares, but {self.state.remaining} remain"
            )


@dataclass(frozen=True, slots=True)
class WantedStop:
    """The stop a sleeve wants on its shares of an instrument, placed when they fill.

    Attributes:
        strategy_id: The sleeve.
        instrument: The shares.
        price: The stop price its strategy asked for at the last decision.
    """

    strategy_id: str
    instrument: Instrument
    price: Money

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        if self.price.currency is not self.instrument.currency or not self.price.is_positive:
            raise ValueError(
                f"wanted stop for {_label(self.strategy_id, self.instrument)}: price must be "
                f"positive, in its currency; got {self.price}"
            )


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """What execution needs to carry on: its working orders and what they are for.

    Attributes:
        orders: Every order not finished, by client order id.
        wanted_stops: The stop each sleeve wants on each instrument.
        last_decision: The close of the last decision handled, or ``None`` before any;
            a decision at or before it is not handled again.
    """

    orders: tuple[WorkingOrder, ...] = ()
    wanted_stops: tuple[WantedStop, ...] = ()
    last_decision: datetime | None = None

    def __post_init__(self) -> None:
        _require_unique(((o.state.order.client_order_id,) for o in self.orders), "working order")
        _require_unique(
            ((w.strategy_id, w.instrument) for w in self.wanted_stops), "wanted stop of a sleeve"
        )
        if self.last_decision is not None:
            _require_aware(self.last_decision, "last_decision")


@dataclass(frozen=True, slots=True)
class AccountRulesState:
    """The account rules' memory: the previous close, the peak and the halt (ADR-0035).

    Attributes:
        last_close: The last session close measured, or ``None`` before any. The next
            run's first close must come after it.
        previous: Equity at that close, one per currency.
        peak: The highest close of equity so far, one per currency.
        halt: The drawdown kill that halted trading, if it triggered. Only a manual
            restart lifts it (``resumed``, ADR-0039); a restart from a checkpoint does
            not.
    """

    last_close: datetime | None = None
    previous: tuple[Money, ...] = ()
    peak: tuple[Money, ...] = ()
    halt: AccountTrigger | None = None

    def __post_init__(self) -> None:
        _require_unique(((m.currency,) for m in self.previous), "previous close per currency")
        _require_unique(((m.currency,) for m in self.peak), "peak per currency")
        if self.last_close is None:
            if self.previous or self.peak or self.halt is not None:
                raise ValueError("account rules with no close measured cannot have a memory")
            return
        _require_aware(self.last_close, "last_close")
        if self.halt is not None:
            if self.halt.rule is not RiskRule.DRAWDOWN_KILL:
                raise ValueError(f"only the drawdown kill halts trading, not {self.halt.rule}")
            if self.halt.at > self.last_close:
                raise ValueError("the halt cannot come after the last close measured")

    def resumed(self) -> AccountRulesState:
        """The memory after a manual restart (``tyche resume``, ADR-0039).

        The halt is lifted and the peak forgotten, so the first close after the restart
        is the new peak and the drawdown kill counts from there: a peak kept would halt
        again at the next close. The previous close stays, so the daily loss limit still
        compares the next close with it.
        """
        return replace(self, peak=(), halt=None)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Everything a run must hand to the next one, as it was when the run ended.

    Attributes:
        run_id: The run that ended in this state.
        saved_at: When it was taken: the run's clock at its end.
        code_version: The Tyche version that took it.
        config_hash: The workspace configuration the run used, if it had one.
        account: Tyche's own view of the account.
        sleeves: The sleeve book.
        execution: Execution's working orders and wanted stops.
        rules: The account rules' memory.
        reconciliation: Reconciliation's memory: the last check and any halt. Empty
            in a checkpoint saved before PR 13, and in a backtest's.

    Raises:
        ValueError: the parts disagree: the sleeves do not add up to the account's
            positions, or a sleeve's resting stop is not a working stop order of that
            sleeve and instrument; or a reconciliation is dated after the checkpoint.
    """

    run_id: str
    saved_at: datetime
    code_version: str
    config_hash: str | None
    account: Account
    sleeves: SleeveState
    execution: ExecutionState
    rules: AccountRulesState
    reconciliation: ReconciliationState = field(default_factory=ReconciliationState)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("a checkpoint needs a run id")
        _require_aware(self.saved_at, "saved_at")
        memory = self.reconciliation
        for moment in (memory.last_at, memory.halt.at if memory.halt else None):
            if moment is not None and moment > self.saved_at:
                raise ValueError(
                    f"checkpoint of {self.run_id}: a reconciliation at {moment.isoformat()} "
                    "comes after it was saved"
                )
        held = {p.instrument: p.quantity for p in self.account.positions}
        for instrument in sorted(
            set(held) | {h.instrument for h in self.sleeves.holdings}, key=str
        ):
            in_book = self.sleeves.total(instrument)
            in_account = held.get(instrument, Decimal(0))
            if in_book != in_account:
                raise ValueError(
                    f"checkpoint of {self.run_id}: the sleeves hold {in_book} {instrument}, "
                    f"the account {in_account}"
                )
        stops = {
            o.state.order.client_order_id: o
            for o in self.execution.orders
            if o.state.order.order_type is OrderType.STOP
        }
        for stop in self.sleeves.stops:
            working = stops.get(stop.client_order_id)
            if (
                working is None
                or working.strategy_id != stop.strategy_id
                or working.state.order.instrument != stop.instrument
            ):
                raise ValueError(
                    f"checkpoint of {self.run_id}: the stop {stop.client_order_id} resting for "
                    f"{_label(stop.strategy_id, stop.instrument)} is not a working stop order "
                    "of that sleeve"
                )


def _require_unique(keys: Iterable[Hashable], what: str) -> None:
    seen: set[Hashable] = set()
    for key in keys:
        if key in seen:
            raise ValueError(f"more than one {what} for {key}")
        seen.add(key)

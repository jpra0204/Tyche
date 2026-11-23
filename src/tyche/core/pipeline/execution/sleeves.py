"""SleeveBook: each strategy's own share of every position (ADR-0022, ADR-0023).

The account holds one position per instrument; the book says how many of those shares
belong to each strategy's sleeve, when the sleeve first bought them, what it paid, and
which protective stop rests at the broker for them. Execution keeps it up to date from
its own fills and crossings, and checks at every decision that the sleeves add up to
the account's positions.

The signals stage reads it through the ``PositionBook`` protocol, so each strategy is
shown only its own positions (ADR-0021).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tyche.core.domain import (
    Instrument,
    Money,
    SleeveHolding,
    SleeveState,
    SleeveStop,
    StrategyPosition,
    require_strategy_id,
)
from tyche.core.domain.account import COST_PLACES


class SleeveBookError(ValueError):
    """An operation would break the book: removing shares a sleeve does not hold."""


@dataclass(frozen=True, slots=True)
class RestingStop:
    """A protective stop order resting at the broker for one sleeve's shares.

    Attributes:
        client_order_id: The stop order.
        price: Its stop price.
    """

    client_order_id: str
    price: Money


@dataclass(frozen=True, slots=True)
class _Holding:
    quantity: Decimal
    cost: Money
    """What the shares cost at their fill or crossing prices, commissions excluded."""
    entry_date: date


type _Key = tuple[str, Instrument]


def _instrument_key(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, instrument.exchange


class SleeveBook:
    """Shares held per sleeve and instrument, with each sleeve's resting stop.

    Implements the signals stage's ``PositionBook``.

    Args:
        start: The book as a previous run left it (ADR-0038), or ``None`` for an empty
            one: a backtest starts with cash only.
    """

    def __init__(self, start: SleeveState | None = None) -> None:
        self._holdings: dict[_Key, _Holding] = {}
        self._stops: dict[_Key, RestingStop] = {}
        if start is not None:
            for h in start.holdings:
                self._holdings[(h.strategy_id, h.instrument)] = _Holding(
                    h.quantity, h.cost, h.entry_date
                )
            for s in start.stops:
                self._stops[(s.strategy_id, s.instrument)] = RestingStop(s.client_order_id, s.price)

    # --- reading -----------------------------------------------------------------

    def held(self, strategy_id: str, instrument: Instrument) -> Decimal:
        """Shares of ``instrument`` the sleeve holds; zero if none."""
        holding = self._holdings.get((strategy_id, instrument))
        return holding.quantity if holding else Decimal(0)

    def total(self, instrument: Instrument) -> Decimal:
        """Shares of ``instrument`` held across every sleeve."""
        return sum(
            (h.quantity for (_, i), h in self._holdings.items() if i == instrument),
            start=Decimal(0),
        )

    @property
    def instruments(self) -> tuple[Instrument, ...]:
        """Every instrument some sleeve holds, by symbol and exchange."""
        held = {instrument for _, instrument in self._holdings}
        return tuple(sorted(held, key=_instrument_key))

    def holders(self, instrument: Instrument) -> tuple[str, ...]:
        """The sleeves holding ``instrument``, by strategy id."""
        return tuple(sorted(s for s, i in self._holdings if i == instrument))

    def stop(self, strategy_id: str, instrument: Instrument) -> RestingStop | None:
        """The stop resting for the sleeve's shares of ``instrument``, if any."""
        return self._stops.get((strategy_id, instrument))

    @property
    def stops(self) -> tuple[tuple[str, Instrument, RestingStop], ...]:
        """Every resting stop, by strategy id, then symbol and exchange."""
        keys = sorted(self._stops, key=lambda k: (k[0], *_instrument_key(k[1])))
        return tuple((s, i, self._stops[(s, i)]) for s, i in keys)

    def positions_of(self, strategy_id: str) -> tuple[StrategyPosition, ...]:
        """The sleeve's positions as its strategy is shown them, by symbol and exchange."""
        mine = sorted(
            (i for s, i in self._holdings if s == strategy_id),
            key=_instrument_key,
        )
        positions: list[StrategyPosition] = []
        for instrument in mine:
            holding = self._holdings[(strategy_id, instrument)]
            stop = self._stops.get((strategy_id, instrument))
            positions.append(
                StrategyPosition(
                    instrument=instrument,
                    quantity=holding.quantity,
                    entry_date=holding.entry_date,
                    entry_price=holding.cost / holding.quantity,
                    stop_price=stop.price if stop else None,
                )
            )
        return tuple(positions)

    def state(self) -> SleeveState:
        """The whole book, for a checkpoint: what a ``SleeveBook(start=...)`` rebuilds."""
        keys = sorted(self._holdings, key=lambda k: (k[0], *_instrument_key(k[1])))
        holdings = tuple(
            SleeveHolding(
                s,
                i,
                self._holdings[(s, i)].quantity,
                self._holdings[(s, i)].cost,
                self._holdings[(s, i)].entry_date,
            )
            for s, i in keys
        )
        stops = tuple(
            SleeveStop(s, i, stop.client_order_id, stop.price) for s, i, stop in self.stops
        )
        return SleeveState(holdings, stops)

    # --- changing ------------------------------------------------------------------

    def add(
        self, strategy_id: str, instrument: Instrument, quantity: Decimal, price: Money, day: date
    ) -> None:
        """Give the sleeve ``quantity`` more shares, bought (or crossed) at ``price`` on ``day``.

        The entry date is that of the first shares; adding to a holding keeps it.
        """
        require_strategy_id(strategy_id)
        if not quantity.is_finite() or quantity <= 0:
            raise SleeveBookError(f"{strategy_id} cannot add {quantity} {instrument}")
        if price.currency is not instrument.currency or not price.is_positive:
            raise SleeveBookError(f"{strategy_id} cannot add {instrument} at {price}")
        key = (strategy_id, instrument)
        held = self._holdings.get(key)
        if held is None:
            self._holdings[key] = _Holding(quantity, price * quantity, day)
        else:
            self._holdings[key] = _Holding(
                held.quantity + quantity, held.cost + price * quantity, held.entry_date
            )

    def remove(self, strategy_id: str, instrument: Instrument, quantity: Decimal) -> None:
        """Take ``quantity`` shares from the sleeve. Its average price is unchanged."""
        key = (strategy_id, instrument)
        held = self._holdings.get(key)
        have = held.quantity if held else Decimal(0)
        if held is None or not quantity.is_finite() or not 0 < quantity <= have:
            raise SleeveBookError(
                f"{strategy_id} cannot give up {quantity} {instrument}: it holds {have}"
            )
        left = held.quantity - quantity
        if left == 0:
            del self._holdings[key]
            return
        cost = (held.cost * left / held.quantity).round_to(COST_PLACES)
        self._holdings[key] = _Holding(left, cost, held.entry_date)

    def set_stop(self, strategy_id: str, instrument: Instrument, stop: RestingStop | None) -> None:
        """Record the stop now resting for the sleeve's shares, or ``None`` for none."""
        key = (strategy_id, instrument)
        if stop is None:
            self._stops.pop(key, None)
        else:
            self._stops[key] = stop

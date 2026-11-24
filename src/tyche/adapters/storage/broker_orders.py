"""SqliteBrokerOrderStore: what a broker adapter sent, in the state database (ADR-0042).

A real broker keeps its own orders while Tyche is stopped, but it does not keep
Tyche's intentions. This store does: every order is written and committed before it
is sent, so after a crash or a lost connection Tyche knows exactly which orders may
have reached the broker, and looks for those before doing anything else. It never
sends one again (ADR-0042).
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tyche.adapters.storage import codec
from tyche.core.domain import OrderState


class BrokerOrderStoreError(Exception):
    """The store refused a change, or holds a row it cannot read."""


class Fate(StrEnum):
    """What Tyche knows about whether an order reached the broker."""

    SENDING = "sending"
    """Written before sending; not yet confirmed by the broker."""

    PLACED = "placed"
    """The broker gave it an order id, or listed it after a reconnection."""

    LOST = "lost"
    """Not listed by the broker after a reconnection. Never resent."""


@dataclass(frozen=True, slots=True)
class BrokerOrderRecord:
    """One order as the adapter remembers it.

    Attributes:
        state: The latest state Tyche published for it.
        fate: Whether it is known to have reached the broker.
        sent_at: When it was written, just before it was sent.
        order_id: The broker's order id, once known.
        perm_id: The broker's permanent id, once known.
        cancel_requested: Tyche asked for it to be cancelled.
    """

    state: OrderState
    fate: Fate
    sent_at: datetime
    order_id: int | None
    perm_id: int | None
    cancel_requested: bool

    @property
    def client_order_id(self) -> str:
        return self.state.order.client_order_id


_COLUMNS = "state, fate, sent_at, order_id, perm_id, cancel_requested, format"
_INSERT = """
INSERT INTO broker_order (client_order_id, sent_at, fate, format, state, updated_at)
VALUES (?, ?, 'sending', ?, ?, ?)
"""
_GET = f"SELECT {_COLUMNS} FROM broker_order WHERE client_order_id = ?"
_ALL = f"SELECT {_COLUMNS} FROM broker_order ORDER BY sent_at, client_order_id"
_FILL_SEEN = "SELECT 1 FROM broker_fill WHERE exec_id = ?"
_FILLS = "SELECT exec_id FROM broker_fill ORDER BY exec_id"
_INSERT_FILL = "INSERT INTO broker_fill (exec_id, client_order_id, published_at) VALUES (?, ?, ?)"


class SqliteBrokerOrderStore:
    """The broker adapter's memory, on a connection from ``open_database``.

    Every change is its own committed transaction, so it is on disk before the
    adapter does the next thing: above all, before an order is sent.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if connection.autocommit is not False:
            raise BrokerOrderStoreError(
                "the broker order store needs a connection from open_database"
            )
        self._connection = connection

    # --- writing ------------------------------------------------------------------

    def record_sending(self, state: OrderState, at: datetime) -> None:
        """Write a new order as ``sending``. Call this before sending it.

        Raises:
            BrokerOrderStoreError: the client order id is already recorded.
        """
        order_id = state.order.client_order_id
        try:
            self._connection.execute(
                _INSERT, (order_id, at.isoformat(), codec.FORMAT, _dump(state), at.isoformat())
            )
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise BrokerOrderStoreError(f"order {order_id} is already recorded") from error
        except BaseException:
            self._connection.rollback()
            raise

    def record_placed(self, client_order_id: str, order_id: int, at: datetime) -> None:
        """The broker accepted the order onto its books with ``order_id``."""
        self._update(
            client_order_id,
            "fate = 'placed', order_id = ?",
            (order_id,),
            at,
            allowed=(Fate.SENDING, Fate.PLACED),
        )

    def record_perm_id(self, client_order_id: str, perm_id: int, at: datetime) -> None:
        """The broker's permanent id for the order."""
        self._update(client_order_id, "perm_id = ?", (perm_id,), at, allowed=(Fate.PLACED,))

    def record_lost(self, client_order_id: str, state: OrderState, at: datetime) -> None:
        """The order was not at the broker after a reconnection, and is now rejected."""
        self._update(
            client_order_id,
            "fate = 'lost', state = ?",
            (_dump(state),),
            at,
            allowed=(Fate.SENDING,),
        )

    def record_state(self, state: OrderState, at: datetime) -> None:
        """The latest state Tyche published for the order."""
        self._update(
            state.order.client_order_id,
            "state = ?",
            (_dump(state),),
            at,
            allowed=(Fate.SENDING, Fate.PLACED),
        )

    def request_cancel(self, client_order_id: str, at: datetime) -> None:
        """Tyche asked for the order to be cancelled."""
        self._update(
            client_order_id,
            "cancel_requested = 1",
            (),
            at,
            allowed=(Fate.SENDING, Fate.PLACED),
        )

    def record_fill(self, exec_id: str, client_order_id: str, at: datetime) -> None:
        """An execution was published as a fill.

        Raises:
            BrokerOrderStoreError: it was recorded already, or its order was not.
        """
        try:
            self._connection.execute(_INSERT_FILL, (exec_id, client_order_id, at.isoformat()))
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise BrokerOrderStoreError(
                f"execution {exec_id} of order {client_order_id} cannot be recorded: {error}"
            ) from error
        except BaseException:
            self._connection.rollback()
            raise

    # --- reading ------------------------------------------------------------------

    def get(self, client_order_id: str) -> BrokerOrderRecord | None:
        row = self._connection.execute(_GET, (client_order_id,)).fetchone()
        return None if row is None else _record(row)

    def all(self) -> tuple[BrokerOrderRecord, ...]:
        """Every order recorded, oldest first."""
        return tuple(_record(row) for row in self._connection.execute(_ALL))

    def unfinished(self) -> tuple[BrokerOrderRecord, ...]:
        """Orders whose last published state is not final, oldest first."""
        return tuple(r for r in self.all() if not r.state.status.is_terminal)

    def fill_seen(self, exec_id: str) -> bool:
        return self._connection.execute(_FILL_SEEN, (exec_id,)).fetchone() is not None

    def fills(self) -> tuple[str, ...]:
        """Every execution id published as a fill."""
        return tuple(str(row[0]) for row in self._connection.execute(_FILLS))

    # --- helpers ------------------------------------------------------------------

    def _update(
        self,
        client_order_id: str,
        assignments: str,
        values: tuple[object, ...],
        at: datetime,
        *,
        allowed: tuple[Fate, ...],
    ) -> None:
        record = self.get(client_order_id)
        if record is None:
            raise BrokerOrderStoreError(f"order {client_order_id} was never recorded")
        if record.fate not in allowed:
            raise BrokerOrderStoreError(
                f"order {client_order_id} is {record.fate}; cannot change it that way"
            )
        try:
            self._connection.execute(
                f"UPDATE broker_order SET {assignments}, updated_at = ? WHERE client_order_id = ?",
                (*values, at.isoformat(), client_order_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise


def _dump(state: OrderState) -> str:
    return json.dumps(codec.encode(state), separators=(",", ":"), sort_keys=True)


def _record(row: tuple[object, ...]) -> BrokerOrderRecord:
    state_text, fate, sent_at, order_id, perm_id, cancel_requested, stored_format = row
    if stored_format != codec.FORMAT:
        raise BrokerOrderStoreError(
            f"a stored order is in format {stored_format}; this Tyche reads {codec.FORMAT}"
        )
    try:
        state = codec.decode(json.loads(str(state_text)))
    except (codec.CodecError, ValueError) as error:
        raise BrokerOrderStoreError(f"a stored order cannot be read: {error}") from error
    if not isinstance(state, OrderState):
        raise BrokerOrderStoreError(f"a stored order holds a {type(state).__name__}")
    return BrokerOrderRecord(
        state=state,
        fate=Fate(str(fate)),
        sent_at=datetime.fromisoformat(str(sent_at)),
        order_id=None if order_id is None else int(str(order_id)),
        perm_id=None if perm_id is None else int(str(perm_id)),
        cancel_requested=bool(cancel_requested),
    )

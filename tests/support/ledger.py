"""Builders for orders and fills in tests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count

from tests.support.market import SPY
from tyche.core.domain import Fill, Instrument, Money, Order, OrderType, Side, TimeInForce

TRADE_DAY = date(2024, 1, 2)
_ids = count(1)


def order(
    side: Side = Side.BUY,
    quantity: str = "10",
    *,
    instrument: Instrument = SPY,
    order_type: OrderType = OrderType.MARKET,
    stop: str | None = None,
    client_order_id: str = "order-1",
) -> Order:
    return Order(
        client_order_id=client_order_id,
        instrument=instrument,
        side=side,
        quantity=Decimal(quantity),
        order_type=order_type,
        time_in_force=TimeInForce.DAY,
        created_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        reason="test",
        stop_price=Money.of(stop, instrument.currency) if stop is not None else None,
    )


def fill(
    side: Side,
    quantity: str | Decimal,
    price: str | Decimal,
    *,
    commission: str | Decimal = "1",
    instrument: Instrument = SPY,
    trade_date: date = TRADE_DAY,
    settle_days: int = 1,
    fill_id: str | None = None,
) -> Fill:
    return Fill(
        fill_id=fill_id or f"fill-{next(_ids)}",
        client_order_id="order-1",
        instrument=instrument,
        side=side,
        quantity=Decimal(quantity),
        price=Money.of(price, instrument.currency),
        commission=Money.of(commission, instrument.currency),
        filled_at=datetime(trade_date.year, trade_date.month, trade_date.day, 14, 30, tzinfo=UTC),
        trade_date=trade_date,
        settles_on=trade_date + timedelta(days=settle_days),
    )

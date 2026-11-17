"""Orders never change; their state moves only along allowed transitions."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from tests.support.ledger import order
from tyche.core.domain import (
    Currency,
    Money,
    OrderError,
    OrderState,
    OrderStatus,
    OrderType,
    Side,
)


class TestOrder:
    def test_holds_its_fields(self) -> None:
        sell = order(Side.SELL, "2.5")

        assert sell.side is Side.SELL
        assert sell.quantity == Decimal("2.5")
        assert sell.stop_price is None

    def test_a_stop_order_carries_its_stop_price(self) -> None:
        stop = order(Side.SELL, order_type=OrderType.STOP, stop="95.50")

        assert stop.stop_price == Money.of("95.50", Currency.USD)

    @pytest.mark.parametrize("quantity", ["0", "-1", "NaN"])
    def test_quantity_must_be_positive(self, quantity: str) -> None:
        with pytest.raises(OrderError, match="quantity must be positive"):
            order(quantity=quantity)

    def test_needs_an_id(self) -> None:
        with pytest.raises(OrderError, match="needs a client_order_id"):
            order(client_order_id="  ")

    def test_creation_time_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            replace(order(), created_at=datetime(2024, 1, 2, 16, 0))  # noqa: DTZ001

    def test_a_stop_order_needs_a_positive_stop_in_the_right_currency(self) -> None:
        with pytest.raises(OrderError, match="needs a stop price"):
            order(order_type=OrderType.STOP)
        with pytest.raises(OrderError, match="stop price must be positive"):
            order(order_type=OrderType.STOP, stop="0")
        with pytest.raises(OrderError, match="stop price is in CAD"):
            replace(
                order(order_type=OrderType.STOP, stop="1"), stop_price=Money.of("1", Currency.CAD)
            )

    def test_only_a_stop_order_has_a_stop_price(self) -> None:
        with pytest.raises(OrderError, match="only a stop order has a stop price"):
            order(stop="95")


class TestLifecycle:
    def accepted(self, quantity: str = "10") -> OrderState:
        return OrderState(order(quantity=quantity)).submit().accept()

    def test_starts_created(self) -> None:
        state = OrderState(order())

        assert state.status is OrderStatus.CREATED
        assert state.remaining == Decimal(10)

    def test_the_happy_path(self) -> None:
        state = self.accepted().fill(Decimal(10))

        assert state.status is OrderStatus.FILLED
        assert state.status.is_terminal
        assert state.remaining == 0

    def test_partial_fills_add_up(self) -> None:
        state = self.accepted().fill(Decimal(3))
        assert state.status is OrderStatus.PARTIALLY_FILLED

        state = state.fill(Decimal(3))
        assert state.status is OrderStatus.PARTIALLY_FILLED
        assert state.filled_quantity == Decimal(6)

        assert state.fill(Decimal(4)).status is OrderStatus.FILLED

    def test_a_fill_cannot_exceed_what_remains(self) -> None:
        with pytest.raises(OrderError, match="exceeds the 7 remaining"):
            self.accepted().fill(Decimal(3)).fill(Decimal(8))

    def test_a_fill_must_be_positive(self) -> None:
        with pytest.raises(OrderError, match="fill quantity must be positive"):
            self.accepted().fill(Decimal(0))

    def test_a_partly_filled_day_order_can_expire(self) -> None:
        state = self.accepted().fill(Decimal(3)).expire()

        assert state.status is OrderStatus.EXPIRED
        assert state.filled_quantity == Decimal(3)

    def test_rejection_keeps_the_reason(self) -> None:
        state = OrderState(order()).submit().reject("insufficient funds")

        assert state.status is OrderStatus.REJECTED
        assert state.note == "insufficient funds"

    def test_an_order_can_be_rejected_before_it_is_sent(self) -> None:
        assert OrderState(order()).reject("risk check").status is OrderStatus.REJECTED

    def test_an_accepted_order_can_be_cancelled(self) -> None:
        assert self.accepted().cancel("kill switch").status is OrderStatus.CANCELLED

    @pytest.mark.parametrize(
        "terminal",
        [
            OrderState(order()).reject("x"),
            OrderState(order()).submit().accept().fill(Decimal(10)),
            OrderState(order()).submit().accept().cancel(),
            OrderState(order()).submit().accept().expire(),
        ],
        ids=["rejected", "filled", "cancelled", "expired"],
    )
    def test_nothing_happens_after_a_terminal_status(self, terminal: OrderState) -> None:
        for move in (terminal.submit, terminal.accept, terminal.expire, terminal.cancel):
            with pytest.raises(OrderError, match="cannot go from"):
                move()
        with pytest.raises(OrderError):
            terminal.fill(Decimal(1))

    @pytest.mark.parametrize(
        ("state", "move"),
        [
            (OrderState(order()), "accept"),
            (OrderState(order()), "cancel"),
            (OrderState(order()).submit(), "expire"),
            (OrderState(order()).submit().accept(), "submit"),
        ],
    )
    def test_skipping_a_step_is_refused(self, state: OrderState, move: str) -> None:
        with pytest.raises(OrderError, match="cannot go from"):
            getattr(state, move)()

    def test_an_order_not_yet_accepted_cannot_fill(self) -> None:
        with pytest.raises(OrderError, match="cannot go from submitted to"):
            OrderState(order()).submit().fill(Decimal(1))

"""Trading events added with execution check their own consistency (ADR-0023)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY
from tyche.core.domain import Account, Currency, Money, PlanLine
from tyche.core.events import AccountEvent, CancelRequestEvent, ExecutionPlanEvent

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
D = Decimal


class TestExecutionPlanEvent:
    def test_lines_are_one_per_sleeve_and_instrument_in_order(self) -> None:
        lines = (
            PlanLine("a", QQQ, D(0), D(5), ordered=D(5)),
            PlanLine("a", SPY, D(1), D(1)),
            PlanLine("b", SPY, D(0), D(2), ordered=D(2)),
        )

        assert ExecutionPlanEvent(AS_OF, lines).lines == lines
        with pytest.raises(ValueError, match="in order"):
            ExecutionPlanEvent(AS_OF, (lines[1], lines[0]))
        with pytest.raises(ValueError, match="in order"):
            ExecutionPlanEvent(AS_OF, (lines[0], lines[0]))

    def test_as_of_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            ExecutionPlanEvent(datetime(2024, 1, 5, 16, 0), ())  # noqa: DTZ001

    def test_sized_on_is_one_amount_per_currency(self) -> None:
        usd = Money.of("690", Currency.USD)
        assert ExecutionPlanEvent(AS_OF, (), (usd,)).sized_on == (usd,)
        with pytest.raises(ValueError, match="more than once"):
            ExecutionPlanEvent(AS_OF, (), (usd, usd))


class TestCancelRequestEvent:
    def test_needs_an_order_and_a_reason(self) -> None:
        assert CancelRequestEvent("stop-1", "replaced").reason == "replaced"
        with pytest.raises(ValueError, match="client_order_id"):
            CancelRequestEvent(" ", "replaced")
        with pytest.raises(ValueError, match="reason"):
            CancelRequestEvent("stop-1", "")


class TestAccountEvent:
    def test_carries_a_snapshot_at_a_utc_moment(self) -> None:
        account = Account.empty().deposit(Money.of("100", Currency.USD))

        assert AccountEvent(AS_OF, account).account == account
        with pytest.raises(ValueError, match="UTC"):
            AccountEvent(datetime(2024, 1, 5, 16, 0), account)  # noqa: DTZ001

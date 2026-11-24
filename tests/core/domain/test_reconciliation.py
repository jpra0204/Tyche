"""Reconciliation's value objects check themselves (ADR-0044)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.support.costs import usd
from tests.support.market import SPY
from tests.support.reconciliation import AT, agreeing, mismatch
from tyche.core.domain import (
    Account,
    BrokerOrder,
    BrokerRecord,
    CashBalance,
    CashCheck,
    CashOutcome,
    Currency,
    InferredFill,
    Money,
    Reconciliation,
    ReconciliationRules,
    ReconciliationState,
    ReconciliationStatus,
    Side,
)


def check(gap: str, outcome: CashOutcome, allowed: str = "1.00") -> CashCheck:
    return CashCheck(
        tyche=usd("100"),
        broker=CashBalance(usd("100") + usd(gap)),
        accrued=usd("0"),
        allowed=usd(allowed),
        outcome=outcome,
    )


class TestRules:
    def test_the_tolerance_is_in_each_currency(self) -> None:
        rules = ReconciliationRules(Decimal("1.00"))
        assert rules.tolerance(Currency.CAD) == Money(Decimal("1.00"), Currency.CAD)

    @pytest.mark.parametrize("value", [Decimal(-1), Decimal("NaN")])
    def test_refuses_a_negative_or_missing_tolerance(self, value: Decimal) -> None:
        with pytest.raises(ValueError, match="cash_tolerance"):
            ReconciliationRules(value)


class TestBrokerRecord:
    def test_an_order_is_listed_once(self) -> None:
        with pytest.raises(ValueError, match="listed twice"):
            BrokerRecord(
                Account.empty(), (BrokerOrder("a", Decimal(1)), BrokerOrder("a", Decimal(2)))
            )

    def test_accrued_dividends_are_never_negative_and_once_per_currency(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            BrokerRecord(Account.empty(), accrued_dividends=(usd("-1"),))
        with pytest.raises(ValueError, match="given twice"):
            BrokerRecord(Account.empty(), accrued_dividends=(usd("1"), usd("2")))

    def test_an_order_has_shares_left(self) -> None:
        with pytest.raises(ValueError, match="remaining must be positive"):
            BrokerOrder("a", Decimal(0))

    def test_accrued_is_zero_when_not_reported(self) -> None:
        assert BrokerRecord(Account.empty()).accrued(Currency.USD) == usd("0")


class TestCashCheck:
    def test_the_outcome_must_fit_the_gap(self) -> None:
        assert check("0", CashOutcome.MATCH).gap == usd("0")
        assert check("-0.5", CashOutcome.ADOPTED).adopted == CashBalance(usd("99.5"))
        with pytest.raises(ValueError, match="a match has no gap"):
            check("0.5", CashOutcome.MATCH)
        with pytest.raises(ValueError, match="adopted needs a gap"):
            check("2", CashOutcome.ADOPTED)
        with pytest.raises(ValueError, match="needs a gap beyond"):
            check("0.5", CashOutcome.EXCEEDED)

    def test_accrued_dividends_count_as_settled_when_adopted(self) -> None:
        found = CashCheck(
            usd("100"), CashBalance(usd("90")), usd("10"), usd("1"), CashOutcome.MATCH
        )
        assert found.adopted == CashBalance(usd("100"))


class TestReconciliation:
    def test_status_follows_what_it_found(self) -> None:
        assert Reconciliation(AT).status is ReconciliationStatus.MATCH
        assert Reconciliation(AT, cash=(check("0.5", CashOutcome.ADOPTED),)).status is (
            ReconciliationStatus.CORRECTED
        )
        assert mismatch(AT).status is ReconciliationStatus.MISMATCH

    def test_an_inferred_fill_prices_its_currencys_gap(self) -> None:
        fill = InferredFill("o", SPY, Side.SELL, Decimal(1), usd("100"))
        with pytest.raises(ValueError, match="prices its currency's cash gap"):
            Reconciliation(AT, inferred=(fill,), cash=(check("0", CashOutcome.MATCH),))
        priced = Reconciliation(AT, inferred=(fill,), cash=(check("100", CashOutcome.PRICED),))
        assert priced.status is ReconciliationStatus.MISMATCH

    def test_needs_a_timezone(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            Reconciliation(AT.replace(tzinfo=None))


class TestMemory:
    def test_only_a_mismatch_halts(self) -> None:
        with pytest.raises(ValueError, match="does not halt"):
            ReconciliationState(halt=Reconciliation(AT))

    def test_a_halt_is_current_until_a_check_agrees_after_it(self) -> None:
        assert ReconciliationState(halt=mismatch(AT)).halt_is_current
        later = ReconciliationState(last_at=AT + timedelta(hours=1), halt=mismatch(AT))
        assert not later.halt_is_current
        assert not ReconciliationState().halt_is_current

    def test_figures_need_a_check(self) -> None:
        with pytest.raises(ValueError, match="figures without a check"):
            ReconciliationState(distributions=(usd("1"),))

    def test_a_checkpoint_starts_with_an_empty_memory(self) -> None:
        assert agreeing().reconciliation == ReconciliationState()

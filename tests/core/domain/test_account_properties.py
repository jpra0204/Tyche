"""Properties of the ledger that must hold for any sequence of trades.

Each test states a rule and lets hypothesis generate hundreds of trade sequences to
try to break it. A failure prints the smallest sequence that breaks the rule.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tests.support.ledger import TRADE_DAY, fill
from tests.support.market import SPY
from tyche.core.domain import Account, Currency, LedgerError, Money, Side

DEPOSIT = Money.of("1000000", Currency.USD)

prices = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000"), places=2)
quantities = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("500"), places=3)
commissions = st.decimals(min_value=Decimal(0), max_value=Decimal("10"), places=2)


@dataclass(frozen=True)
class Trade:
    side: Side
    quantity: Decimal
    price: Decimal
    commission: Decimal
    settle_days: int


trades = st.lists(
    st.builds(
        Trade,
        side=st.sampled_from(Side),
        quantity=quantities,
        price=prices,
        commission=commissions,
        settle_days=st.integers(min_value=0, max_value=3),
    ),
    max_size=30,
)


def replay(sequence: list[Trade]) -> tuple[Account, list[Money]]:
    """Apply the trades in order. A sale is cut to what is held; skipped if nothing is."""
    account = Account.empty().deposit(DEPOSIT)
    flows: list[Money] = []
    for day, trade in enumerate(sequence):
        quantity = trade.quantity
        if trade.side is Side.SELL:
            held = account.position(SPY)
            if held is None:
                continue
            quantity = min(quantity, held.quantity)
        executed = fill(
            trade.side,
            quantity,
            trade.price,
            commission=trade.commission,
            trade_date=TRADE_DAY + timedelta(days=day),
            settle_days=trade.settle_days,
        )
        account = account.apply_fill(executed)
        flows.append(executed.cash_flow)
    return account, flows


@given(trades)
def test_cash_is_conserved_exactly(sequence: list[Trade]) -> None:
    account, flows = replay(sequence)

    expected = DEPOSIT
    for flow in flows:
        expected += flow
    assert account.cash(Currency.USD).total == expected


@given(trades)
def test_holdings_never_go_below_zero(sequence: list[Trade]) -> None:
    account, _ = replay(sequence)

    position = account.position(SPY)
    assert position is None or position.quantity > 0


@given(trades, st.integers(min_value=0, max_value=40))
def test_settling_moves_cash_but_never_changes_the_total(sequence: list[Trade], days: int) -> None:
    account, _ = replay(sequence)
    settled = account.settle(through=TRADE_DAY + timedelta(days=days))

    before, after = account.cash(Currency.USD), settled.cash(Currency.USD)
    assert after.total == before.total
    assert after.settled + after.unsettled == after.total
    assert all(p.settles_on > TRADE_DAY + timedelta(days=days) for p in after.pending)


@given(trades)
def test_cash_equals_deposit_plus_realised_profit_minus_cost_still_held(
    sequence: list[Trade],
) -> None:
    """Every dollar is either still cash, tied up in shares at cost, or already gained or lost."""
    account, _ = replay(sequence)

    position = account.position(SPY)
    cost_held = position.cost if position else Money.zero(Currency.USD)
    assert (
        account.cash(Currency.USD).total == DEPOSIT + account.realized_pnl(Currency.USD) - cost_held
    )


@given(quantities, prices, commissions, commissions)
def test_a_round_trip_at_one_price_loses_exactly_the_commissions(
    quantity: Decimal, price: Decimal, buy_fee: Decimal, sell_fee: Decimal
) -> None:
    account = (
        Account.empty()
        .deposit(DEPOSIT)
        .apply_fill(fill(Side.BUY, quantity, price, commission=buy_fee))
        .apply_fill(fill(Side.SELL, quantity, price, commission=sell_fee))
    )

    fees = Money.of(buy_fee + sell_fee, Currency.USD)
    assert account.realized_pnl(Currency.USD) == -fees
    assert account.cash(Currency.USD).total == DEPOSIT - fees
    assert account.position(SPY) is None


@given(trades, quantities, prices)
def test_a_purchase_beyond_the_cash_is_always_refused(
    sequence: list[Trade], quantity: Decimal, price: Decimal
) -> None:
    account, _ = replay(sequence)
    cash_before = account.cash(Currency.USD)
    position_before = account.position(SPY)
    affordable = cash_before.total
    too_many = (affordable.amount / price).to_integral_value() + quantity + 1

    try:
        account.apply_fill(
            fill(Side.BUY, too_many, price, commission="0", trade_date=date(2030, 1, 2))
        )
    except LedgerError:
        pass
    else:
        raise AssertionError("a purchase beyond the cash was accepted")
    assert account.cash(Currency.USD) == cash_before
    assert account.position(SPY) == position_before

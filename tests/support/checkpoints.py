"""A small checkpoint built by hand: two sleeves in SPY, a resting stop, a working order."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from tests.support.costs import usd
from tests.support.ledger import fill, order
from tests.support.market import SPY
from tyche.core.domain import (
    Account,
    AccountRulesState,
    AccountTrigger,
    Checkpoint,
    ExecutionState,
    OrderState,
    OrderType,
    OwedShares,
    RiskRule,
    Side,
    SleeveHolding,
    SleeveState,
    SleeveStop,
    TimeInForce,
    WantedStop,
    WorkingOrder,
)

SAVED_AT = datetime(2024, 1, 3, 21, 0, tzinfo=UTC)
LAST_CLOSE = SAVED_AT


def account() -> Account:
    bought = fill(Side.BUY, "10", "470", trade_date=date(2024, 1, 2), fill_id="sim-000001")
    return Account.empty().deposit(usd("10000")).apply_fill(bought).mark(SPY, usd("475"))


def stop_order() -> WorkingOrder:
    stop = replace(
        order(
            Side.SELL,
            "6",
            order_type=OrderType.STOP,
            stop="440",
            client_order_id="sim-000001-stop-alpha",
        ),
        time_in_force=TimeInForce.GTC,
    )
    return WorkingOrder(OrderState(stop).submit().accept(), strategy_id="alpha")


def market_order() -> WorkingOrder:
    buy = order(Side.BUY, "3", client_order_id="20240103T210000Z-SPY.ARCX-buy")
    return WorkingOrder(OrderState(buy).submit().accept(), owed=(OwedShares("beta", Decimal(3)),))


def sleeves() -> SleeveState:
    return SleeveState(
        holdings=(
            SleeveHolding("alpha", SPY, Decimal(6), usd("2820"), date(2024, 1, 2)),
            SleeveHolding("beta", SPY, Decimal(4), usd("1880"), date(2024, 1, 2)),
        ),
        stops=(SleeveStop("alpha", SPY, "sim-000001-stop-alpha", usd("440")),),
    )


def rules(*, halted: bool = False) -> AccountRulesState:
    halt = AccountTrigger(
        RiskRule.DRAWDOWN_KILL,
        LAST_CLOSE,
        usd("10500"),
        usd("8900"),
        Decimal("0.15"),
        "equity fell 15% below its peak",
    )
    return AccountRulesState(
        last_close=LAST_CLOSE,
        previous=(usd("9999"),),
        peak=(usd("10500"),),
        halt=halt if halted else None,
    )


def checkpoint(run_id: str = "paper-2024-01-03", *, saved_at: datetime = SAVED_AT) -> Checkpoint:
    return Checkpoint(
        run_id=run_id,
        saved_at=saved_at,
        code_version="0.1.0+gtest",
        config_hash="abc123",
        account=account(),
        sleeves=sleeves(),
        execution=ExecutionState(
            orders=(market_order(), stop_order()),
            wanted_stops=(WantedStop("alpha", SPY, usd("440")),),
            last_decision=LAST_CLOSE,
        ),
        rules=rules(halted=True),
    )

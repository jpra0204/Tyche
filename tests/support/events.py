"""Events a backtest on clean data rarely publishes, for tests that must cover every type."""

from datetime import UTC, date, datetime
from decimal import Decimal

from tests.support.costs import usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    AccountTrigger,
    CashBalance,
    CashCheck,
    CashDistribution,
    CashOutcome,
    DataIssue,
    DataIssueKind,
    Difference,
    DifferenceKind,
    DistributionKind,
    EndedOrder,
    InferredFill,
    Kill,
    OrderAdjustment,
    OrderType,
    PendingCash,
    Reconciliation,
    RiskAction,
    RiskRule,
    Side,
    Sleeve,
    SleeveStatus,
    Timeframe,
)
from tyche.core.events import (
    ApprovedPortfolioEvent,
    CycleSkippedEvent,
    DataQualityEvent,
    DistributionEvent,
    Event,
    ReconciliationEvent,
    ResumeEvent,
    RiskEvent,
    SkipReason,
)

CLOSE = datetime(2024, 3, 18, 20, 0, tzinfo=UTC)

DRAWDOWN = AccountTrigger(
    rule=RiskRule.DRAWDOWN_KILL,
    at=CLOSE,
    reference=usd("10000"),
    equity=usd("8400"),
    limit=Decimal("0.15"),
    reason="equity 16% below its peak",
)

MISMATCH = Reconciliation(
    at=datetime(2024, 3, 19, 0, 5, tzinfo=UTC),
    differences=(
        Difference(DifferenceKind.UNKNOWN_ORDER, "paper-1-QQQ", "the broker has it working"),
    ),
    inferred=(InferredFill("paper-0-SPY-stop-trend", SPY, Side.SELL, Decimal(3), usd("498.25")),),
    ended=(EndedOrder("paper-0-QQQ-stop-trend", QQQ, OrderType.STOP),),
    cash=(
        CashCheck(
            tyche=usd("1000"),
            broker=CashBalance(
                usd("2000"), (PendingCash(usd("-505.25"), date(2024, 3, 20), "ibkr-2024-03-20"),)
            ),
            accrued=usd("0"),
            allowed=usd("1.00"),
            outcome=CashOutcome.PRICED,
        ),
    ),
)

FLATTEN = Kill(
    "stopping everything", flatten=True, engaged_at=datetime(2024, 3, 18, 21, 4, tzinfo=UTC)
)


def rare_events() -> tuple[Event, ...]:
    """One of each event, or event shape, that clean simulated data does not produce."""
    return (
        DistributionEvent(
            CashDistribution(SPY, date(2024, 3, 15), usd("1.59"), DistributionKind.DIVIDEND)
        ),
        DataQualityEvent(
            DataIssue(
                DataIssueKind.SUSPECT_MOVE, SPY, date(2024, 3, 14), "close moved 31% in a day"
            )
        ),
        RiskEvent(as_of=CLOSE, profile="stage-1", adjustment=DRAWDOWN),
        RiskEvent(
            as_of=CLOSE,
            profile="stage-1",
            adjustment=OrderAdjustment(
                rule=RiskRule.MAX_ORDER_VALUE,
                action=RiskAction.SHRINK,
                instrument=SPY,
                before=Decimal(12),
                after=Decimal(9),
                limit=usd("5000"),
                reason="the order would exceed the maximum order value",
            ),
        ),
        ApprovedPortfolioEvent(
            as_of=CLOSE,
            sleeves=(Sleeve("rotation", Decimal(1), SleeveStatus.FAILED, error="no data"),),
            targets=(),
            profile="stage-1",
            halt=DRAWDOWN,
        ),
        ApprovedPortfolioEvent(
            as_of=CLOSE,
            sleeves=(Sleeve("rotation", Decimal(1), SleeveStatus.FAILED, error="no data"),),
            targets=(),
            profile="stage-1",
            halt=DRAWDOWN,
            kill=FLATTEN,
        ),
        ResumeEvent("looked at it, carrying on", kill=FLATTEN, halt=DRAWDOWN, after_run="paper-1"),
        ApprovedPortfolioEvent(
            as_of=datetime(2024, 3, 19, 20, 0, tzinfo=UTC),
            sleeves=(Sleeve("trend", Decimal("0.5"), SleeveStatus.FAILED, error="no data"),),
            targets=(),
            profile="stage-1",
            kill=FLATTEN,
            unreconciled=MISMATCH,
        ),
        ReconciliationEvent(MISMATCH),
        ResumeEvent(
            "sold by the stop overnight",
            after_run="paper-2",
            reconciliation=MISMATCH,
            applied=True,
        ),
        CycleSkippedEvent(
            timeframe=Timeframe.D1,
            as_of=CLOSE,
            reason=SkipReason.INCOMPLETE,
            trade_until=datetime(2024, 3, 19, 13, 0, tzinfo=UTC),
            delivered=(SPY,),
            missing=(QQQ,),
        ),
    )

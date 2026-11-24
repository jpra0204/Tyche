"""Events a backtest on clean data rarely publishes, for tests that must cover every type."""

from datetime import UTC, date, datetime
from decimal import Decimal

from tests.support.costs import usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    AccountTrigger,
    CashDistribution,
    DataIssue,
    DataIssueKind,
    DistributionKind,
    Kill,
    OrderAdjustment,
    RiskAction,
    RiskRule,
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
        CycleSkippedEvent(
            timeframe=Timeframe.D1,
            as_of=CLOSE,
            reason=SkipReason.INCOMPLETE,
            trade_until=datetime(2024, 3, 19, 13, 0, tzinfo=UTC),
            delivered=(SPY,),
            missing=(QQQ,),
        ),
    )

"""``RiskAdjustment``: one change the risk gate made, and why (ADR-0033)."""

from decimal import Decimal

import pytest

from tests.support.market import SPY
from tyche.core.domain import RiskAction, RiskAdjustment, RiskRule, RiskScope


def adjustment(
    before: str = "0.5", after: str = "0.2", action: RiskAction = RiskAction.SHRINK
) -> RiskAdjustment:
    return RiskAdjustment(
        RiskRule.MAX_POSITION_SIZE,
        RiskScope.ACCOUNT,
        action,
        "a",
        SPY,
        Decimal(before),
        Decimal(after),
        Decimal("0.2"),
        "too big",
    )


def test_a_shrink_lowers_a_weight() -> None:
    assert adjustment().after == Decimal("0.2")


def test_a_block_approves_nothing() -> None:
    assert adjustment(after="0", action=RiskAction.BLOCK).after == 0


@pytest.mark.parametrize(
    ("before", "after", "action", "message"),
    [
        ("0.2", "0.2", RiskAction.SHRINK, "only lowers"),
        ("0.2", "0.3", RiskAction.SHRINK, "only lowers"),
        ("0.5", "0", RiskAction.SHRINK, "only a block"),
        ("0.5", "0.2", RiskAction.BLOCK, "only a block"),
        ("0.5", "-0.1", RiskAction.SHRINK, "at least 0"),
    ],
)
def test_refuses_what_is_not_a_cut(
    before: str, after: str, action: RiskAction, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        adjustment(before, after, action)


def test_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="needs a reason"):
        RiskAdjustment(
            RiskRule.MAX_POSITION_SIZE,
            RiskScope.ACCOUNT,
            RiskAction.SHRINK,
            "a",
            SPY,
            Decimal("0.5"),
            Decimal("0.2"),
            Decimal("0.2"),
            " ",
        )

"""Which events become alerts, and how a run's alerts are collected (ADR-0040)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.core.domain.test_risk import adjustment
from tests.core.risk.test_gate import AS_OF, daily_loss, drawdown, proposal
from tests.support.kill import kill
from tests.support.market import QQQ, SPY
from tests.support.recording import TickingClock
from tyche.core.domain import DataIssue, DataIssueKind
from tyche.core.events import (
    ApprovedPortfolioEvent,
    DataQualityEvent,
    Event,
    EventBus,
    RiskEvent,
    RunMode,
)
from tyche.core.pipeline.alerts import (
    MAX_ISSUES_LISTED,
    AlertCollector,
    channel_check_alert,
    data_failure_alert,
    kill_alert,
    resumed_alert,
    risk_limit_alert,
    run_failed_alert,
)
from tyche.core.ports import AlertKind

NOW = datetime(2026, 11, 23, 21, 30, tzinfo=UTC)


def issue(day: int = 20, kind: DataIssueKind = DataIssueKind.MISSING_SESSION) -> DataIssue:
    return DataIssue(kind, SPY, date(2026, 11, day), "no bar for an open session")


class TestRiskLimitAlert:
    def test_the_drawdown_kill_says_trading_is_halted_and_how_to_resume(self) -> None:
        alert = risk_limit_alert(RiskEvent(AS_OF, "stage-1", drawdown()), NOW)
        assert alert is not None
        assert alert.kind is AlertKind.RISK_LIMIT
        assert alert.title == "Drawdown kill: trading is halted"
        assert alert.at == NOW
        assert alert.lines[0] == (
            "Equity 8000 USD at the close of 2024-01-05, down 20.00% from 10000 USD (limit 15.00%)."
        )
        assert alert.lines[1] == "Risk profile: stage-1."
        assert "`tyche resume`" in alert.lines[2]

    def test_the_daily_loss_limit_says_exits_still_work(self) -> None:
        alert = risk_limit_alert(RiskEvent(AS_OF, "default", daily_loss()), NOW)
        assert alert is not None
        assert alert.title == "Daily loss limit reached"
        assert "down 5.00%" in alert.lines[0]
        assert "Exits and reductions still go through" in alert.lines[2]

    def test_a_routine_cut_is_not_an_alert(self) -> None:
        assert risk_limit_alert(RiskEvent(AS_OF, "default", adjustment()), NOW) is None


class TestOtherAlerts:
    def test_a_kill_from_the_command(self) -> None:
        alert = kill_alert(kill(flatten=True, reason="markets in chaos"), NOW)
        assert alert.kind is AlertKind.KILL_SWITCH
        assert alert.title == "Kill switch engaged with flatten"
        assert alert.lines[0] == "Reason: markets in chaos"
        assert "Every holding is sold at the next open" in alert.lines[1]

    def test_a_kill_found_by_a_run_names_the_decision(self) -> None:
        alert = kill_alert(kill(), NOW, decision=AS_OF)
        assert alert.title == "Kill switch engaged at the decision of 2024-01-05"
        assert alert.lines[1] == "No new orders. Holdings are kept; resting stops stay."

    def test_a_resume(self) -> None:
        alert = resumed_alert("checked", NOW, released=kill(), lifted=drawdown())
        assert alert.kind is AlertKind.RESUMED
        assert alert.title == "Trading resumed: lifted the kill switch and the drawdown halt"
        assert "The peak is forgotten" in alert.lines[-1]

    def test_a_resume_of_the_switch_alone_says_nothing_of_the_peak(self) -> None:
        alert = resumed_alert("checked", NOW, released=kill(), lifted=None)
        assert alert.title == "Trading resumed: lifted the kill switch"
        assert not any("peak" in line for line in alert.lines)

    def test_data_problems_listed_up_to_a_limit(self) -> None:
        issues = [issue(1 + n % 28) for n in range(MAX_ISSUES_LISTED + 3)]
        alert = data_failure_alert(issues, NOW)
        assert alert.title == f"Market data: {MAX_ISSUES_LISTED + 3} problems found"
        assert len(alert.lines) == MAX_ISSUES_LISTED + 1
        assert alert.lines[-1] == "… and 3 more in the journal."

    def test_one_data_problem(self) -> None:
        alert = data_failure_alert([issue()], NOW)
        assert alert.title == "Market data: 1 problem found"
        assert alert.lines == (str(issue()),)

    def test_data_failure_needs_an_issue(self) -> None:
        with pytest.raises(ValueError, match="at least one issue"):
            data_failure_alert([], NOW)

    def test_a_failed_run(self) -> None:
        alert = run_failed_alert("r1", RunMode.PAPER, "Yahoo did not answer", NOW)
        assert alert.kind is AlertKind.RUN_FAILED
        assert alert.lines[:2] == ("Run r1 (paper).", "Error: Yahoo did not answer")

    def test_the_channel_check_says_nothing_happened(self) -> None:
        alert = channel_check_alert(NOW)
        assert alert.kind is AlertKind.TEST
        assert "Nothing happened in trading" in alert.lines[0]


class TestCollector:
    def run(self, *events: Event) -> AlertCollector:
        bus = EventBus(TickingClock(NOW).now)
        collector = AlertCollector(bus)
        for event in events:
            bus.publish(event, source="test")
        bus.drain()
        return collector

    def test_collects_risk_limits_in_order_and_skips_routine_cuts(self) -> None:
        collector = self.run(
            RiskEvent(AS_OF, "default", daily_loss()),
            RiskEvent(AS_OF, "default", adjustment()),
            RiskEvent(AS_OF + timedelta(days=1), "default", drawdown()),
        )
        assert [a.title for a in collector.alerts()] == [
            "Daily loss limit reached",
            "Drawdown kill: trading is halted",
        ]

    def test_the_alert_time_is_when_the_event_was_published(self) -> None:
        collector = self.run(RiskEvent(AS_OF, "default", drawdown()))
        assert collector.alerts()[0].at == NOW

    def test_the_kill_switch_once_per_run(self) -> None:
        sleeves = proposal({SPY: {"a": "0.1"}, QQQ: {"a": "0.1"}}).sleeves
        killed = ApprovedPortfolioEvent(AS_OF, sleeves, (), "default", kill=kill())
        later = ApprovedPortfolioEvent(
            AS_OF + timedelta(days=1), sleeves, (), "default", kill=kill()
        )
        collector = self.run(killed, later)
        assert [a.kind for a in collector.alerts()] == [AlertKind.KILL_SWITCH]

    def test_an_approval_without_the_switch_is_no_alert(self) -> None:
        sleeves = proposal({SPY: {"a": "0.1"}}).sleeves
        collector = self.run(ApprovedPortfolioEvent(AS_OF, sleeves, (), "default"))
        assert collector.alerts() == ()

    def test_every_data_problem_in_one_alert_last(self) -> None:
        collector = self.run(
            DataQualityEvent(issue(18)),
            RiskEvent(AS_OF, "default", drawdown()),
            DataQualityEvent(issue(19)),
        )
        kinds = [a.kind for a in collector.alerts()]
        assert kinds == [AlertKind.RISK_LIMIT, AlertKind.DATA_FAILURE]
        assert collector.alerts()[-1].lines == (str(issue(18)), str(issue(19)))

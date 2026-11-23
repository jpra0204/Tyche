"""``tyche capital``'s wiring: every amount under both plans, the record and the report.

The cache is filled the way `tyche data fetch` fills it, from scripted Yahoo answers,
for SPY from October 2019 to November 2024: it climbs from USD 300 and swings in
waves, and the bars after 2023 lie inside the holdout. The workspace runs buy-and-hold
of SPY alone.
"""

import json
import math
import shutil
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.workspace import add_unbound_profile, keep_candidates
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import YFinanceSource
from tyche.config import TycheConfig, Workspace, init_workspace, load_config
from tyche.core.backtest import CapitalError, HoldoutError, trial_key
from tyche.core.domain import AssetClass
from tyche.core.sim import SimClock
from tyche.runtime.backtest import CodeVersion
from tyche.runtime.capital import (
    FIXED,
    TIERED,
    CapitalOutcome,
    CapitalRequest,
    SizedRun,
    run_configured_capital,
)
from tyche.runtime.capital_report import is_capital, read_capital, write_capital_report
from tyche.runtime.data import CALENDAR_START, fetch_daily_histories, instrument_for
from tyche.runtime.report import REPORT_FILE, ReportError
from tyche.runtime.trials import CAPITAL_FILE, recorded_trial_keys

NYSE = ExchangeCalendarsCalendar("XNYS", first=CALENDAR_START, last=date(2025, 1, 31))
CACHED_FROM, CACHED_TO = date(2019, 10, 1), date(2024, 11, 29)
FIRST, LAST = date(2021, 1, 4), date(2023, 12, 29)
NOW = SimClock(datetime(2024, 12, 2, 12, 0, tzinfo=UTC))
CODE = CodeVersion("0.0.0", "0123456789abcdef0123", dirty=False)
REQUEST = CapitalRequest(
    amounts=(Decimal(200), Decimal(1000), Decimal(5000)),
    reference=Decimal(100_000),
    tolerance=Decimal("0.005"),
    positions=3,
)


def workspace(root: Path) -> TycheConfig:
    home = root / "home"
    home.mkdir()
    ws = init_workspace(home / "ws", user_home=home)
    keep_candidates(ws.root, "SPY")
    config = load_config(Workspace(ws.root), add_unbound_profile(ws.root))
    days = [s.day for s in NYSE.sessions_between(CACHED_FROM, CACHED_TO)]
    spy = [row(d, 300 + i * 0.05 + 25 * math.sin(i / 40)) for i, d in enumerate(days)]
    outcomes = fetch_daily_histories(
        config,
        [instrument_for("SPY", "ARCX", AssetClass.ETF, config.market_profile)],
        CACHED_FROM,
        CACHED_TO,
        source=YFinanceSource({"XNYS": NYSE}, fetch=FakeFetch(spy)),
        clock=NOW,
    )
    assert all(o.error is None for o in outcomes)
    return config


def analyse(config: TycheConfig, request: CapitalRequest = REQUEST) -> CapitalOutcome:
    return run_configured_capital(config, request, FIRST, LAST, clock=NOW, code=CODE)


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> CapitalOutcome:
    return analyse(workspace(tmp_path_factory.mktemp("capital")))


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    return workspace(tmp_path)


def read(path: Path) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


class TestTheRequest:
    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"amounts": ()}, "give at least one amount"),
            ({"amounts": (Decimal(0),)}, "must be positive"),
            ({"amounts": (Decimal(500), Decimal(500))}, "each amount may be given once"),
            ({"amounts": (Decimal(1000), Decimal(500))}, "smallest first"),
            ({"reference": Decimal(5000)}, "must be larger than every amount"),
            ({"tolerance": Decimal("-0.01")}, "the tolerance must be at least 0"),
            ({"positions": 0}, "positions must be at least 1"),
        ],
    )
    def test_is_checked_before_anything_runs(self, change: dict[str, Any], message: str) -> None:
        with pytest.raises(CapitalError, match=message):
            replace(REQUEST, **change)

    def test_the_holdout_is_refused(self, config: TycheConfig) -> None:
        with pytest.raises(HoldoutError):
            run_configured_capital(config, REQUEST, FIRST, date(2024, 6, 28), clock=NOW, code=CODE)

    def test_nothing_to_analyse_without_a_budget(self, config: TycheConfig) -> None:
        bare = replace(config, strategies=())

        with pytest.raises(CapitalError, match="no strategy has a budget"):
            analyse(bare)


class TestTheRuns:
    def test_every_amount_runs_under_both_plans(self, analysed: CapitalOutcome) -> None:
        (study,) = analysed.result.studies

        assert study.strategy_id == "buy_and_hold"
        assert [v.plan for v in study.verdicts] == [FIXED, TIERED]
        for verdict in study.verdicts:
            assert [r.amount for r in verdict.runs] == list(REQUEST.amounts)
            assert verdict.reference.amount == REQUEST.reference
            assert all(r.metrics is not None for r in (*verdict.runs, verdict.reference))

    def test_each_run_starts_from_its_own_amount(self, analysed: CapitalOutcome) -> None:
        for verdict in analysed.result.studies[0].verdicts:
            for run in (*verdict.runs, verdict.reference):
                assert run.metrics is not None
                assert run.metrics.strategy.start_equity == run.amount

    def test_tiered_costs_less_than_fixed_on_a_small_account(
        self, analysed: CapitalOutcome
    ) -> None:
        fixed, tiered = analysed.result.studies[0].verdicts
        assert fixed.runs[1].drag is not None
        assert tiered.runs[1].drag is not None

        assert tiered.runs[1].drag.commission < fixed.runs[1].drag.commission

    def test_an_account_below_one_share_holds_nothing(self, analysed: CapitalOutcome) -> None:
        # USD 200 never buys a share of an ETF priced above USD 270.
        smallest = analysed.result.studies[0].verdicts[0].runs[0]

        assert smallest.metrics is not None
        assert smallest.metrics.strategy.exposure == 0
        assert smallest.short_of_a_share == smallest.decisions > 0

    def test_the_minimum_is_the_smallest_viable_amount(self, analysed: CapitalOutcome) -> None:
        for verdict in analysed.result.studies[0].verdicts:
            viable = [verdict.viable(r, REQUEST.tolerance) for r in verdict.runs]
            assert viable[0] is False
            assert viable[-1] is True
            assert verdict.minimum == next(
                r.amount for r, ok in zip(verdict.runs, viable, strict=True) if ok
            )

    def test_today_reads_the_latest_close_even_inside_the_holdout(
        self, analysed: CapitalOutcome
    ) -> None:
        (latest,) = analysed.result.latest_closes

        assert str(latest.instrument) == "SPY@ARCX"
        assert latest.day == CACHED_TO
        assert latest.close is not None

    def test_progress_is_told_about_every_run(self, config: TycheConfig) -> None:
        told: list[tuple[SizedRun, SizedRun | None]] = []
        run_configured_capital(
            config,
            replace(REQUEST, amounts=(Decimal(1000),)),
            FIRST,
            LAST,
            clock=NOW,
            code=CODE,
            progress=lambda run, reference: told.append((run, reference)),
        )

        # The reference first, then the amount, for each plan.
        assert [(r.plan, r.amount, ref is None) for r, ref in told] == [
            (FIXED, REQUEST.reference, True),
            (FIXED, Decimal(1000), False),
            (TIERED, REQUEST.reference, True),
            (TIERED, Decimal(1000), False),
        ]

    def test_a_costs_file_without_tiered_compares_nothing(self, config: TycheConfig) -> None:
        outcome = analyse(
            replace(config, tiered_costs=None), replace(REQUEST, amounts=(Decimal(1000),))
        )

        assert [v.plan for v in outcome.result.studies[0].verdicts] == [FIXED]


class TestTheRecord:
    def test_is_written_to_reports_capital(self, analysed: CapitalOutcome) -> None:
        assert analysed.record_dir.parent.name == "capital"
        assert is_capital(analysed.record_dir)
        assert sorted(p.name for p in analysed.record_dir.iterdir()) == [CAPITAL_FILE]

    def test_states_the_request_the_plans_and_every_run(self, analysed: CapitalOutcome) -> None:
        record = read(analysed.record_dir / CAPITAL_FILE)

        assert record["request"] == {
            "amounts": ["200", "1000", "5000"],
            "reference": "100000",
            "tolerance": "0.005",
            "positions": 3,
        }
        assert set(record["plans"]) == {FIXED, TIERED}
        assert record["plans"][TIERED]["exchange_fee_per_share"] == "0.0030"
        (study,) = record["strategies"]
        fixed = study["plans"][0]
        assert [r["amount"] for r in fixed["runs"]] == ["200", "1000", "5000"]
        assert fixed["runs"][0]["viable"] is False
        assert "size_penalty" not in fixed["reference"]
        assert record["benchmark"]["instrument"] == "SPY@ARCX"
        assert record["config_hash"].startswith("sha256:")
        assert record["range"] == {"first": FIRST.isoformat(), "last": LAST.isoformat()}

    def test_states_the_trial_it_ran(self, analysed: CapitalOutcome) -> None:
        record = read(analysed.record_dir / CAPITAL_FILE)
        (study,) = record["strategies"]
        parameters = {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"}

        assert study["key"] == trial_key("buy_and_hold", study["version"], parameters)
        reports = analysed.record_dir.parent.parent
        assert recorded_trial_keys(reports, "buy_and_hold") == {study["key"]}

    def test_holds_the_arithmetic(self, analysed: CapitalOutcome) -> None:
        record = read(analysed.record_dir / CAPITAL_FILE)
        trips = record["round_trips"]["plans"][FIXED]

        assert [row["amount"] for row in trips] == ["200", "1000", "5000"]
        # USD 200 in three positions of USD 66.67 cannot buy a USD 100 share.
        assert trips[0]["by_positions"]["3"] is None
        assert trips[2]["by_positions"]["1"] is not None
        (spy,) = record["today"]["candidates"]
        assert spy["day"] == CACHED_TO.isoformat()
        assert spy["shares"]["200"] == 0


class TestTheReport:
    def test_is_built_from_the_record_alone(self, analysed: CapitalOutcome) -> None:
        page = write_capital_report(analysed.record_dir)

        assert page == analysed.record_dir / REPORT_FILE
        html = page.read_text(encoding="utf-8")
        for heading in (
            "The answer",
            "buy_and_hold",
            "What one round trip costs",
            "Today&#x27;s share prices",
            "What ran",
            "Data and its limits",
        ):
            assert heading in html
        assert "IBKR Pro Tiered" in html

    def test_records_and_warns_of_runs_the_drawdown_kill_halted(
        self, analysed: CapitalOutcome, tmp_path: Path
    ) -> None:
        record = read(analysed.record_dir / CAPITAL_FILE)
        plan = record["strategies"][0]["plans"][0]
        assert plan["runs"][0]["halted_at"] is None
        copy = tmp_path / "capital"
        shutil.copytree(analysed.record_dir, copy)
        plan["runs"][0]["halted_at"] = "2021-03-04T21:00:00+00:00"
        (copy / CAPITAL_FILE).write_text(json.dumps(record))

        html = write_capital_report(copy).read_text(encoding="utf-8")

        assert "The drawdown kill halted 1 of " in html
        assert "buy_and_hold at " in html
        assert "(2021-03-04)" in html

    def test_refuses_a_record_of_another_format(self, tmp_path: Path) -> None:
        (tmp_path / CAPITAL_FILE).write_text('{"capital_format": 99}', encoding="utf-8")

        with pytest.raises(ReportError, match="format 99"):
            read_capital(tmp_path)


class TestATooLargeReference:
    def test_is_flagged_when_the_volume_cap_binds(self, config: TycheConfig) -> None:
        # A USD 10 billion account cannot buy its SPY at the open within 1% of a bar's
        # volume, so its orders expire part-filled.
        outcome = analyse(
            config, replace(REQUEST, amounts=(Decimal(5000),), reference=Decimal(10**10))
        )
        fixed = outcome.result.studies[0].verdicts[0]

        assert fixed.reference.cut_short > 0
        assert fixed.reference_too_large
        assert fixed.runs[0].cut_short == 0
        record = read(outcome.record_dir / CAPITAL_FILE)
        assert record["strategies"][0]["plans"][0]["reference_too_large"] is True
        html = write_capital_report(outcome.record_dir).read_text(encoding="utf-8")
        assert "the reference account is too large for this strategy" in html

    def test_is_not_flagged_otherwise(self, analysed: CapitalOutcome) -> None:
        for verdict in analysed.result.studies[0].verdicts:
            assert not verdict.reference_too_large

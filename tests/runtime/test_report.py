"""``report.html``, written from a run's record alone (ADR-0028).

The record comes from the same scripted backtest as ``test_backtest``: SPY and QQQ in
late 2023, buy-and-hold on SPY.
"""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tests.runtime.test_backtest import backtest
from tests.runtime.test_backtest import config as config  # the fixture
from tyche.adapters.reports import Table, render_html
from tyche.config import TycheConfig
from tyche.core.backtest import cost_drag
from tyche.runtime.report import (
    REPORT_FILE,
    ReportError,
    backtest_report,
    read_record,
    write_report,
)


@pytest.fixture
def folder(config: TycheConfig) -> Path:
    return backtest(config).record_dir


def test_is_written_into_the_record_folder(folder: Path) -> None:
    path = write_report(folder)

    assert path == folder / REPORT_FILE
    page = path.read_text(encoding="utf-8")
    for title in (
        "Summary",
        "Year by year",
        "Trading",
        "Cost drag",
        "What ran",
        "Data and its limits",
    ):
        assert f"<h2>{title}</h2>" in page
    assert folder.name in page
    assert "One backtest is not a verdict." in page
    assert page.count('<figure class="chart">') == 4


def test_needs_nothing_outside_the_file(folder: Path) -> None:
    page = write_report(folder).read_text(encoding="utf-8")

    for outside in ("<script", "<link", 'src="http', "url(http", "@import"):
        assert outside not in page


def test_rebuilding_gives_the_same_file(folder: Path) -> None:
    first = write_report(folder).read_bytes()

    assert write_report(folder).read_bytes() == first


def test_the_cost_drag_adds_up_to_the_record(folder: Path) -> None:
    record = read_record(folder)
    metrics = json.loads((folder / "metrics.json").read_text())

    commission = sum((cost.commission for cost in record.costs), Decimal(0))
    assert commission.quantize(Decimal("0.01")) == Decimal(metrics["trading"]["costs"])
    assert record.slippage_bps == Decimal(5)
    assert all(cost.slippage > 0 for cost in record.costs)
    drag = cost_drag(record.equity, record.costs)
    [section] = [s for s in backtest_report(record).sections if s.title == "Cost drag"]
    [table, *_] = [b for b in section.blocks if isinstance(b, Table)]
    assert ("Total costs", f"{drag.total:,.2f} USD") in table.rows
    assert drag.total == drag.commission + drag.slippage


def test_says_so_when_the_folder_is_not_a_record(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"is not a backtest record: run\.json is missing"):
        write_report(tmp_path)


def test_an_unmeasured_run_has_no_report(folder: Path) -> None:
    run = json.loads((folder / "run.json").read_text())
    run["outcome"]["metrics"] = None
    run["outcome"]["metrics_error"] = "the run halted before its first close"
    (folder / "run.json").write_text(json.dumps(run))

    with pytest.raises(ReportError, match="not measured, so it has no report: the run halted"):
        write_report(folder)


def test_names_the_risk_profile_and_what_the_gate_cut(folder: Path) -> None:
    page = write_report(folder).read_text(encoding="utf-8")

    assert "default: risk per trade 1.00%, at most 5 positions of at most 20.00% each" in page
    assert "The gate shrank " in page


def test_names_money_caps_and_the_purchases_they_cut_when_a_run_applied_them(
    folder: Path,
) -> None:
    run = json.loads((folder / "run.json").read_text())
    run["risk"]["money_caps"] = {"USD": {"max_total_capital": "690", "max_order_value": "690"}}
    run["outcome"]["risk_adjustments"]["max_order_value.shrink"] = 2
    (folder / "run.json").write_text(json.dumps(run))

    page = write_report(folder).read_text(encoding="utf-8")

    assert "money caps capital 690 and order 690 USD" in page
    assert "the money caps cut 2 purchases" in page


def test_a_record_from_before_the_risk_gate_says_so(folder: Path) -> None:
    run = json.loads((folder / "run.json").read_text())
    del run["risk"]
    del run["outcome"]["risk_adjustments"]
    (folder / "run.json").write_text(json.dumps(run))

    page = write_report(folder).read_text(encoding="utf-8")

    assert "recorded before the risk gate" in page


def test_a_record_of_another_format_is_refused(folder: Path) -> None:
    run = json.loads((folder / "run.json").read_text())
    run["record_format"] = 99
    (folder / "run.json").write_text(json.dumps(run))

    with pytest.raises(ReportError, match="record format 99, this version of Tyche reads format 1"):
        write_report(folder)


def test_a_damaged_record_is_refused(folder: Path) -> None:
    (folder / "equity.csv").write_text("close_utc,equity\nnot a date,1\n")

    with pytest.raises(ReportError, match="cannot read the record"):
        write_report(folder)


def test_a_metrics_file_of_another_format_is_refused(folder: Path) -> None:
    metrics = json.loads((folder / "metrics.json").read_text())
    metrics["metrics_format"] = 7
    (folder / "metrics.json").write_text(json.dumps(metrics))

    with pytest.raises(ReportError, match=r"metrics\.json is format 7"):
        write_report(folder)


def test_a_record_without_its_slippage_is_refused(folder: Path) -> None:
    run = json.loads((folder / "run.json").read_text())
    del run["config"]["config/costs/US.toml"]["slippage_bps"]
    (folder / "run.json").write_text(json.dumps(run))

    with pytest.raises(ReportError, match="does not say which slippage the run used"):
        write_report(folder)


def test_a_halted_run_an_unrecovered_fall_and_an_outside_benchmark_are_all_said(
    folder: Path,
) -> None:
    record = read_record(folder)
    run = json.loads(json.dumps(record.run))
    run["outcome"]["completed"] = False
    run["outcome"]["failure"] = "a stage failed"
    run["benchmark"]["data"] = {**run["benchmark"]["data"], "instrument": "IVV@ARCX"}
    metrics = json.loads(json.dumps(record.metrics))
    metrics["strategy"]["max_drawdown"] = {
        "depth": "0.1",
        "peak": "2023-11-01T20:00:00+00:00",
        "trough": "2023-11-10T21:00:00+00:00",
        "recovered": None,
    }
    metrics["benchmark"]["max_drawdown"] = None

    page = render_html(backtest_report(replace(record, run=run, metrics=metrics)))

    assert "The run halted: a stage failed" in page
    assert "not recovered by the end of the run" in page
    assert "none, it never closed below a previous high" in page
    assert "<td>IVV@ARCX</td>" in page

"""``report.html``: a backtest's record, read back and turned into a report (ADR-0028).

The report is built from the record folder alone (``run.json``, ``metrics.json``,
``equity.csv`` and ``fills.csv``), never from the cache or a second run. So it can be
written for any run ever recorded, rebuilt after the report itself changes, and it
can never show a number the record does not hold.

Sections: a summary against the benchmark, with equity and drawdown charts; the
return of each calendar year; trading and exposure; the cost drag (ADR-0028); what
ran; and the data used with the limits every result shares.

Composition-root code (ADR-0004): it reads files, asks the core to compute the cost
drag and the yearly returns, and hands a ``Document`` to the HTML renderer.
"""

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tyche.adapters.reports import (
    Block,
    Bullets,
    Callout,
    Chart,
    Document,
    Line,
    Paragraph,
    Section,
    Table,
    Tone,
    render_html,
)
from tyche.core.backtest import (
    CostDrag,
    EquityPoint,
    FillCost,
    MetricsError,
    YearReturn,
    cost_drag,
    fill_cost,
    yearly_returns,
)
from tyche.core.domain import Side
from tyche.runtime.backtest import METRICS_FORMAT, RECORD_FORMAT

REPORT_FILE = "report.html"


class ReportError(ValueError):
    """The folder is not a record a report can be written from."""


@dataclass(frozen=True, slots=True)
class Record:
    """One run's record, read back.

    Attributes:
        folder: Where it is.
        run: ``run.json``.
        metrics: ``metrics.json``.
        equity: The run's equity at every close.
        benchmark: The benchmark's equity at the same closes.
        costs: Every fill's costs, slippage included.
        slippage_bps: The slippage rate the run used.
    """

    folder: Path
    run: dict[str, Any]
    metrics: dict[str, Any]
    equity: tuple[EquityPoint, ...]
    benchmark: tuple[EquityPoint, ...]
    costs: tuple[FillCost, ...]
    slippage_bps: Decimal


def write_report(folder: Path) -> Path:
    """Write ``report.html`` into a run's record folder, replacing any older one."""
    record = read_record(folder)
    try:
        document = backtest_report(record)
    except MetricsError as error:
        raise ReportError(f"{folder}: {error}") from None
    path = folder / REPORT_FILE
    path.write_text(render_html(document), encoding="utf-8")
    return path


def read_record(folder: Path) -> Record:
    """Read a record folder, or raise ``ReportError`` saying what is wrong with it."""
    run = _json(folder / "run.json", "is not a backtest record: run.json is missing")
    if run.get("record_format") != RECORD_FORMAT:
        raise ReportError(
            f"{folder}: run.json is record format {run.get('record_format')}, "
            f"this version of Tyche reads format {RECORD_FORMAT}"
        )
    outcome = run.get("outcome", {})
    if outcome.get("metrics") is None:
        reason = outcome.get("metrics_error") or "metrics.json was not written"
        raise ReportError(f"{folder}: the run was not measured, so it has no report: {reason}")
    metrics = _json(folder / "metrics.json", "metrics.json is missing")
    if metrics.get("metrics_format") != METRICS_FORMAT:
        raise ReportError(
            f"{folder}: metrics.json is format {metrics.get('metrics_format')}, "
            f"this version of Tyche reads format {METRICS_FORMAT}"
        )
    slippage = _slippage_bps(run, folder)
    try:
        equity, benchmark = _equity(folder / "equity.csv")
        costs = _costs(folder / "fills.csv", slippage)
    except (KeyError, ValueError, InvalidOperation, MetricsError) as error:
        raise ReportError(f"{folder}: cannot read the record: {error}") from None
    return Record(folder, run, metrics, equity, benchmark, costs, slippage)


def _json(path: Path, missing: str) -> dict[str, Any]:
    if not path.is_file():
        raise ReportError(f"{path.parent}: {missing}")
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


def _slippage_bps(run: dict[str, Any], folder: Path) -> Decimal:
    costs = [v for k, v in run.get("config", {}).items() if k.startswith("config/costs/")]
    if len(costs) != 1 or "slippage_bps" not in costs[0]:
        raise ReportError(f"{folder}: run.json does not say which slippage the run used")
    return Decimal(costs[0]["slippage_bps"])


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def _equity(path: Path) -> tuple[tuple[EquityPoint, ...], tuple[EquityPoint, ...]]:
    equity: list[EquityPoint] = []
    benchmark: list[EquityPoint] = []
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            at = _moment(row["close_utc"])
            equity.append(EquityPoint(at, Decimal(row["equity"]), Decimal(row["invested"])))
            bench = Decimal(row["benchmark_equity"])
            benchmark.append(EquityPoint(at, bench, bench))
    return tuple(equity), tuple(benchmark)


def _costs(path: Path, slippage_bps: Decimal) -> tuple[FillCost, ...]:
    with path.open(newline="", encoding="utf-8") as file:
        return tuple(
            fill_cost(
                _moment(row["filled_at_utc"]),
                Side(row["side"]),
                Decimal(row["quantity"]),
                Decimal(row["price"]),
                Decimal(row["commission"]),
                slippage_bps,
            )
            for row in csv.DictReader(file)
        )


# --- the document ---------------------------------------------------------------------


def backtest_report(record: Record) -> Document:
    """The report's content, as a document the renderer can draw."""
    run, metrics = record.run, record.metrics
    drag = cost_drag(record.equity, record.costs)
    strategies = ", ".join(f"{s['id']} ({_percent_of(s['budget'])})" for s in run["strategies"])
    span = run["range"]
    starting = run["starting_cash"]
    subtitle = (
        f"{span['first_session']} to {span['last_session']}, {span['sessions']:,} sessions. "
        f"Strategies: {strategies}. Starting cash {_amount(starting['amount'])} "
        f"{starting['currency']}."
    )
    callouts = [
        Callout(
            "One backtest is not a verdict. A result better than the benchmark may be "
            "luck, or the best of many tries. Out-of-sample results and a correction for "
            "the number of trials come before any claim of an edge; this report has "
            "neither."
        )
    ]
    if run["code"]["git_dirty"]:
        callouts.append(
            Callout(
                "The code had uncommitted changes, so its commit alone does not reproduce "
                "this run.",
                Tone.WARNING,
            )
        )
    if not run["outcome"]["completed"]:
        callouts.append(Callout(f"The run halted: {run['outcome']['failure']}", Tone.WARNING))
    return Document(
        title=f"Backtest {run['run_id']}",
        subtitle=subtitle,
        callouts=tuple(callouts),
        sections=(
            _summary(record),
            _years(record),
            _trading(record),
            _cost_drag(record, drag),
            _what_ran(run),
            _data(run, metrics),
        ),
    )


def _summary(record: Record) -> Section:
    metrics = record.metrics
    mine, bench, diff = metrics["strategy"], metrics["benchmark"], metrics["versus_benchmark"]
    currency = metrics["currency"]
    rows = (
        (
            "Final equity",
            f"{_amount(mine['end_equity'])} {currency}",
            f"{_amount(bench['end_equity'])} {currency}",
            "",
        ),
        (
            "Total return",
            _pct(mine["total_return"]),
            _pct(bench["total_return"]),
            _points(diff["total_return"]),
        ),
        ("CAGR", _pct(mine["cagr"]), _pct(bench["cagr"]), _points(diff["cagr"])),
        (
            "Volatility",
            _pct(mine["volatility"]),
            _pct(bench["volatility"]),
            _points(diff["volatility"]),
        ),
        (
            "Sharpe (rf 0)",
            _ratio(mine["sharpe"]),
            _ratio(bench["sharpe"]),
            _ratio(diff["sharpe"], sign=True),
        ),
        (
            "Sortino (rf 0)",
            _ratio(mine["sortino"]),
            _ratio(bench["sortino"]),
            _ratio(diff["sortino"], sign=True),
        ),
        (
            "Max drawdown",
            _pct(_depth(mine)),
            _pct(_depth(bench)),
            _points(diff["max_drawdown"]),
        ),
        ("Exposure", _pct(mine["exposure"]), _pct(bench["exposure"]), ""),
    )
    benchmark_name = f"{bench['instrument']} total return"
    blocks: list[Block] = [
        Paragraph(
            f"Your strategies together, against the benchmark, {bench['instrument']}'s "
            f"{bench['method']}. Both start "
            "from the same equity at the same first close and are measured on the same "
            "closes. Differences are in percentage points. Sharpe and Sortino use a "
            "risk-free rate of zero, as cash earns nothing in the simulator, so compare "
            "them with each other, not with published figures."
        ),
        Table(("", "Strategies", benchmark_name, "Difference"), rows),
        Paragraph(_drawdown_sentence("Your strategies' worst fall", mine["max_drawdown"])),
        Paragraph(_drawdown_sentence("The benchmark's", bench["max_drawdown"])),
        Chart(
            "Equity",
            (_line("Strategies", record.equity), _line(benchmark_name, record.benchmark)),
            metrics["currency"],
            log_scale=True,
        ),
        Chart(
            "Drawdown: fall from the highest close so far",
            (
                _drawdown_line("Strategies", record.equity),
                _drawdown_line(benchmark_name, record.benchmark),
            ),
            "below peak",
            percent=True,
            shade=True,
        ),
        Paragraph("The equity chart's scale is logarithmic: equal heights are equal percentages."),
    ]
    return Section("Summary", tuple(blocks))


def _years(record: Record) -> Section:
    mine = yearly_returns(record.equity)
    bench = {year.year: year for year in yearly_returns(record.benchmark)}
    rows = tuple(
        (
            str(year.year),
            _covers(year),
            _pct(year.value),
            _pct(bench[year.year].value),
            _points(year.value - bench[year.year].value),
        )
        for year in mine
    )
    return Section(
        "Year by year",
        (
            Paragraph(
                "Each year runs from the last close of the year before (the first close, for "
                "the first year) to its own last close. The first and last years are usually "
                "partial: the second column says which closes each covers."
            ),
            Table(
                ("Year", "Closes", "Strategies", "Benchmark", "Difference"), rows, numeric_from=2
            ),
        ),
    )


def _trading(record: Record) -> Section:
    trading = record.metrics["trading"]
    outcome = record.run["outcome"]
    win_rate = _pct(trading["win_rate"]) if trading["win_rate"] is not None else "none closed"
    rows = (
        ("Fills", f"{outcome['fills']:,}"),
        ("Closed trades", f"{trading['closed_trades']:,}"),
        ("Win rate", win_rate),
        ("Still open at the end", f"{trading['still_open']:,}"),
        ("Turnover", _turnover(trading["turnover"])),
        ("Traded", f"{_amount(trading['traded'])} {record.metrics['currency']}"),
        ("Free-riding violations", f"{outcome['free_riding']:,}"),
    )
    exposure = Line(
        "Invested",
        tuple((p.at, float(p.invested / p.equity)) for p in record.equity),
    )
    return Section(
        "Trading",
        (
            Paragraph(
                "A trade runs from the fill that opens a position in an instrument to the fill "
                "that closes it, across all strategies; its profit includes commissions and "
                "fees, not dividends. Turnover counts both sides: the value of every fill over "
                "the average equity, per year."
            ),
            Table(("", ""), rows),
            Chart(
                "Invested: share of equity in positions",
                (exposure,),
                "invested",
                percent=True,
                shade=True,
            ),
        ),
    )


def _cost_drag(record: Record, drag: CostDrag) -> Section:
    currency = record.metrics["currency"]
    start = record.equity[0].equity
    rows = (
        ("Commission and regulatory fees", _money(drag.commission, currency)),
        (
            f"Slippage ({_plain(record.slippage_bps)} bps a fill)",
            _money(drag.slippage, currency),
        ),
        ("Total costs", _money(drag.total, currency)),
        ("Total, as a share of the starting equity", _pct(drag.total / start)),
        ("Per year, as a share of the average equity", _pct(drag.per_year)),
        (
            "Share of the profit before costs",
            _pct(drag.share_of_gross_profit)
            if drag.share_of_gross_profit is not None
            else "no profit before costs",
        ),
        ("CAGR before costs", _pct(drag.before_costs.cagr)),
        ("CAGR after costs", _pct(drag.after_costs.cagr)),
        ("Cost drag on CAGR", _points(drag.cagr_drag)),
    )
    return Section(
        "Cost drag",
        (
            Paragraph(
                "What trading costs took. Every cost paid up to a close is added back onto "
                "the equity at that close, which gives the run before costs; both are measured "
                "the same way. Slippage is worked back from each fill's price at the run's "
                "slippage rate."
            ),
            Table(("", ""), rows),
            Callout(
                "Costs are added back as paid, not compounded: money not spent on costs would "
                "have grown too. The drag shown is therefore a floor, most of all on a small "
                "account that trades often."
            ),
            Chart(
                "Equity before and after costs",
                (
                    _line("After costs (as it happened)", record.equity),
                    _line("Before costs", drag.before_costs_points),
                ),
                currency,
                log_scale=True,
            ),
        ),
    )


def _what_ran(run: dict[str, Any]) -> Section:
    code = run["code"]
    commit = code["git_commit"] or "unknown"
    version = f"{code['tyche_version']}, commit {commit[:12]}"
    if code["git_dirty"]:
        version += ", with uncommitted changes"
    costs = next(v for k, v in run["config"].items() if k.startswith("config/costs/"))
    commission = costs["commission"]
    execution = run["execution"]
    warm_up = run["warm_up"]
    rows = (
        ("Run", run["run_id"]),
        ("Started", run["started_at"]),
        ("Code", f"Tyche {version}; Python {code['python']}"),
        ("Config hash", run["config_hash"]),
        ("Market profile", run["market_profile"]),
        ("Range asked for", f"{run['range']['first']} to {run['range']['last']}"),
        (
            "Warm-up",
            (
                f"{warm_up['sessions']} sessions from {warm_up['first']} "
                f"({warm_up['sessions_needed']} needed)"
            )
            if warm_up["first"]
            else f"none ({warm_up['sessions_needed']} needed)",
        ),
        ("Holdout", f"from {run['holdout_starts']}, never used by a backtest"),
        (
            "Execution",
            f"rebalance band {execution['rebalance_band']}, "
            f"price buffer {execution['price_buffer']}",
        ),
        (
            "Costs",
            f"{commission['per_share']} a share, at least {commission['minimum']}, at most "
            f"{_pct(commission['maximum_rate'])} of the order; "
            f"slippage {costs['slippage_bps']} bps; "
            f"T+{costs['settlement_days']}; rates checked {run['costs_checked_on']}",
        ),
    )
    strategies = tuple(
        (s["id"], s["plugin"] or "", s["version"], _percent_of(s["budget"]))
        for s in run["strategies"]
    )
    return Section(
        "What ran",
        (
            Paragraph(
                "Everything needed to run this again: run.json in the same folder holds the "
                "full configuration, and the config hash identifies it."
            ),
            Table(("", ""), rows),
            Table(("Strategy", "Plugin", "Version", "Budget"), strategies, numeric_from=3),
        ),
    )


def _data(run: dict[str, Any], metrics: dict[str, Any]) -> Section:
    used = list(run["data"])
    if run["benchmark"]["data"]["instrument"] not in {d["instrument"] for d in used}:
        used.append(run["benchmark"]["data"])
    rows = tuple(
        (
            d["instrument"],
            d["source"],
            f"{d['bars']:,}",
            _day(d["first_bar"]),
            _day(d["last_bar"]),
            _day(d["fetched_to"]),
            f"{d['issues']:,}",
            f"{d['distributions']:,}",
            f"{d['splits']:,}",
        )
        for d in used
    )
    limits = (
        "Yahoo Finance data, through the unofficial yfinance library: for personal use "
        "only, and it can change, be revised or stop working without notice.",
        "Prices are split-adjusted; dividends are cash, credited at the open of the "
        "ex-date (before the real payment date) with no withholding tax.",
        "Survivorship bias: the backtest can only trade the instruments listed today, all "
        "of which still exist. It never meets a fund that closed.",
        "Market orders fill at the official open, moved by a fixed slippage. A real order "
        "at the open can fill elsewhere, and there is no market impact beyond a cap of 1% "
        "of the bar's volume.",
        "A stop is assumed to fill whenever the day's low reaches it, at the stop price, or "
        "at the open if the open is already through it: daily bars do not say when the low "
        "happened.",
        "Cash earns no interest, and Sharpe and Sortino use a risk-free rate of zero.",
        "Commissions are IBKR Pro Fixed as checked on "
        f"{run['costs_checked_on']}; brokers change their prices.",
        "No currency conversion: the account, the instruments and the costs are all in "
        f"{metrics['currency']}.",
        "Everything here is in-sample: one run over one stretch of history.",
    )
    return Section(
        "Data and its limits",
        (
            Paragraph(
                "The history this run read, from the workspace's cache. Data issues are "
                "sessions the audit found missing, conflicting or suspect; the dates are "
                "listed by tyche data fetch. Sessions before an instrument existed count as "
                "missing."
            ),
            Table(
                (
                    "Instrument",
                    "Source",
                    "Bars",
                    "First bar",
                    "Last bar",
                    "Fetched",
                    "Issues",
                    "Dividends",
                    "Splits",
                ),
                rows,
                numeric_from=2,
            ),
            Paragraph("Limits every result in this report shares:"),
            Bullets(limits),
        ),
    )


# --- formatting -----------------------------------------------------------------------


def _line(label: str, points: Sequence[EquityPoint]) -> Line:
    return Line(label, tuple((p.at, float(p.equity)) for p in points))


def _drawdown_line(label: str, points: Sequence[EquityPoint]) -> Line:
    peak = points[0].equity
    values: list[tuple[datetime, float]] = []
    for point in points:
        peak = max(peak, point.equity)
        values.append((point.at, float(point.equity / peak - 1)))
    return Line(label, tuple(values))


def _drawdown_sentence(whose: str, drawdown: dict[str, Any] | None) -> str:
    if drawdown is None:
        return f"{whose}: none, it never closed below a previous high."
    recovered = (
        f"back at the peak on {_day(drawdown['recovered'])}"
        if drawdown["recovered"]
        else "not recovered by the end of the run"
    )
    return (
        f"{whose}: {_pct(drawdown['depth'])}, from {_day(drawdown['peak'])} to "
        f"{_day(drawdown['trough'])}; {recovered}."
    )


def _depth(series: dict[str, Any]) -> str | None:
    drawdown = series["max_drawdown"]
    return drawdown["depth"] if drawdown else "0"


def _covers(year: YearReturn) -> str:
    return f"{year.first.date().isoformat()} to {year.last.date().isoformat()}"


def _day(moment: str | None) -> str:
    return "" if moment is None else date.fromisoformat(moment[:10]).isoformat()


def _number(value: str | Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _pct(value: str | Decimal | None) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{number * 100:.2f}%"


def _points(value: str | Decimal | None) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{number * 100:+.2f} pts"


def _ratio(value: str | Decimal | None, *, sign: bool = False) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    return f"{number:+.2f}" if sign else f"{number:.2f}"


def _turnover(value: str | None) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{number:.2f} a year"


def _amount(value: str) -> str:
    return f"{Decimal(value):,.2f}"


def _money(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}"


def _plain(value: Decimal) -> str:
    """A decimal without trailing zeros: 5, 0.5, 12.25."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _percent_of(budget: str) -> str:
    return f"{_plain(Decimal(budget) * 100)}% of equity"

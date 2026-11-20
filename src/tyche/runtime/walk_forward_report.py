"""``report.html`` for a walk-forward, built from its record alone (ADR-0029).

Like a backtest's report (ADR-0028), it reads only the record folder: the
walk-forward's ``walk_forward.json``, ``metrics.json`` and ``equity.csv``, and each
fold's ``metrics.json`` and ``run.json``. It never reads the cache or runs anything.

Sections: the test windows chained, against the benchmark; every fold's in-sample and
out-of-sample results side by side; trading in the test windows; what ran; and the
limits every result shares, with those a walk-forward adds.

Composition-root code (ADR-0004): it reads files and hands a ``Document`` to the HTML
renderer.
"""

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tyche.adapters.reports import (
    Block,
    Bullets,
    Callout,
    Chart,
    Document,
    Paragraph,
    Section,
    Table,
    Tone,
    render_html,
)
from tyche.core.backtest import EquityPoint, MetricsError
from tyche.runtime.backtest import METRICS_FORMAT, RECORD_FORMAT
from tyche.runtime.report import (
    REPORT_FILE,
    ReportError,
    data_limits,
    depth_of,
    drawdown_line,
    drawdown_sentence,
    equity_line,
    fmt_amount,
    fmt_budget,
    fmt_pct,
    fmt_points,
    fmt_ratio,
)
from tyche.runtime.walk_forward import WALK_FORWARD_FILE, WALK_FORWARD_FORMAT


@dataclass(frozen=True, slots=True)
class FoldRecord:
    """One fold's two windows, read back from their records."""

    number: int
    train_run: dict[str, Any]
    train: dict[str, Any]
    test_run: dict[str, Any]
    test: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WalkForwardRecord:
    """A walk-forward's record, read back.

    Attributes:
        folder: Where it is.
        study: ``walk_forward.json``.
        metrics: ``metrics.json``: the test windows chained.
        equity: The chained equity at every test close.
        benchmark: The chained benchmark at the same closes.
        folds: Every finished fold's two windows.
    """

    folder: Path
    study: dict[str, Any]
    metrics: dict[str, Any]
    equity: tuple[EquityPoint, ...]
    benchmark: tuple[EquityPoint, ...]
    folds: tuple[FoldRecord, ...]


def is_walk_forward(folder: Path) -> bool:
    """True if ``folder`` holds a walk-forward's record rather than a backtest's."""
    return (folder / WALK_FORWARD_FILE).is_file()


def write_walk_forward_report(folder: Path) -> Path:
    """Write ``report.html`` into a walk-forward's folder, replacing any older one."""
    record = read_walk_forward(folder)
    path = folder / REPORT_FILE
    path.write_text(render_html(walk_forward_report(record)), encoding="utf-8")
    return path


def read_walk_forward(folder: Path) -> WalkForwardRecord:
    """Read a walk-forward's folder, or raise ``ReportError`` saying what is wrong."""
    study = _json(folder / WALK_FORWARD_FILE, folder)
    if study.get("walk_forward_format") != WALK_FORWARD_FORMAT:
        raise ReportError(
            f"{folder}: {WALK_FORWARD_FILE} is format {study.get('walk_forward_format')}, "
            f"this version of Tyche reads format {WALK_FORWARD_FORMAT}"
        )
    outcome = study.get("outcome", {})
    if outcome.get("metrics") is None:
        reason = outcome.get("failure") or "metrics.json was not written"
        raise ReportError(
            f"{folder}: the walk-forward did not finish, so it has no report: {reason}"
        )
    metrics = _json(folder / "metrics.json", folder)
    if metrics.get("walk_forward_format") != WALK_FORWARD_FORMAT:
        raise ReportError(
            f"{folder}: metrics.json is format {metrics.get('walk_forward_format')}, "
            f"this version of Tyche reads format {WALK_FORWARD_FORMAT}"
        )
    folds = tuple(_fold(folder, fold) for fold in study["folds"] if fold["finished"])
    try:
        equity, benchmark = _equity(folder / "equity.csv")
    except (KeyError, ValueError, InvalidOperation, MetricsError) as error:
        raise ReportError(f"{folder}: cannot read the record: {error}") from None
    return WalkForwardRecord(folder, study, metrics, equity, benchmark, folds)


def _fold(folder: Path, fold: dict[str, Any]) -> FoldRecord:
    windows: list[dict[str, Any]] = []
    for kind in ("train", "test"):
        where = folder / fold[kind]["record"]
        run = _json(where / "run.json", where)
        measured = _json(where / "metrics.json", where)
        if run.get("record_format") != RECORD_FORMAT:
            raise ReportError(f"{where}: run.json is record format {run.get('record_format')}")
        if measured.get("metrics_format") != METRICS_FORMAT:
            raise ReportError(f"{where}: metrics.json is format {measured.get('metrics_format')}")
        windows += [run, measured]
    return FoldRecord(fold["number"], *windows)


def _json(path: Path, folder: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReportError(f"{folder}: {path.name} is missing")
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


def _equity(path: Path) -> tuple[tuple[EquityPoint, ...], tuple[EquityPoint, ...]]:
    equity: list[EquityPoint] = []
    benchmark: list[EquityPoint] = []
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            at = datetime.fromisoformat(row["close_utc"]).astimezone(UTC)
            equity.append(EquityPoint(at, Decimal(row["equity"]), Decimal(row["invested"])))
            bench = Decimal(row["benchmark_equity"])
            benchmark.append(EquityPoint(at, bench, bench))
    return tuple(equity), tuple(benchmark)


# --- the document ---------------------------------------------------------------------


def walk_forward_report(record: WalkForwardRecord) -> Document:
    """The report's content, as a document the renderer can draw."""
    study = record.study
    scheme = study["scheme"]
    span = study["range"]
    strategies = ", ".join(f"{s['id']} ({fmt_budget(s['budget'])})" for s in study["strategies"])
    folds = record.folds
    subtitle = (
        f"{span['first']} to {span['last']}, {len(folds)} folds, {scheme['described']}. "
        f"Strategies: {strategies}. Every window starts from "
        f"{fmt_amount(study['starting_cash']['amount'])} {study['starting_cash']['currency']}."
    )
    callouts = [
        Callout(
            "Out-of-sample here means only that no test window was part of the training "
            "window before it. The train step kept the configured parameters, so nothing "
            "was chosen on the training windows: the test windows run the same "
            "strategies in shorter, fresh-started pieces. The gap between in-sample and "
            "out-of-sample results therefore shows how results change from one period to "
            "the next, not overfitting. It measures overfitting once parameters are "
            "chosen on each training window (parameter sweeps)."
        ),
        Callout(
            "Rules chosen by people who have seen this history, or read research about "
            "it, are never fully out-of-sample on it. Only the holdout, from "
            f"{study['holdout_starts']}, is history no experiment has used."
        ),
    ]
    if study["code"]["git_dirty"]:
        callouts.append(
            Callout(
                "The code had uncommitted changes, so its commit alone does not reproduce "
                "this walk-forward.",
                Tone.WARNING,
            )
        )
    return Document(
        title=f"Walk-forward {study['walk_forward_id']}",
        subtitle=subtitle,
        callouts=tuple(callouts),
        sections=(
            _out_of_sample(record),
            _fold_by_fold(record),
            _trading(record),
            _what_ran(record),
            _limits(record),
        ),
    )


def _out_of_sample(record: WalkForwardRecord) -> Section:
    metrics = record.metrics
    mine, bench, diff = metrics["out_of_sample"], metrics["benchmark"], metrics["versus_benchmark"]
    currency = metrics["currency"]
    benchmark_name = f"{bench['instrument']} total return"
    rows = (
        (
            "Final equity",
            f"{fmt_amount(mine['end_equity'])} {currency}",
            f"{fmt_amount(bench['end_equity'])} {currency}",
            "",
        ),
        (
            "Total return",
            fmt_pct(mine["total_return"]),
            fmt_pct(bench["total_return"]),
            fmt_points(diff["total_return"]),
        ),
        ("CAGR", fmt_pct(mine["cagr"]), fmt_pct(bench["cagr"]), fmt_points(diff["cagr"])),
        (
            "Volatility",
            fmt_pct(mine["volatility"]),
            fmt_pct(bench["volatility"]),
            fmt_points(diff["volatility"]),
        ),
        (
            "Sharpe (rf 0)",
            fmt_ratio(mine["sharpe"]),
            fmt_ratio(bench["sharpe"]),
            fmt_ratio(diff["sharpe"], sign=True),
        ),
        (
            "Sortino (rf 0)",
            fmt_ratio(mine["sortino"]),
            fmt_ratio(bench["sortino"]),
            fmt_ratio(diff["sortino"], sign=True),
        ),
        (
            "Max drawdown",
            fmt_pct(depth_of(mine)),
            fmt_pct(depth_of(bench)),
            fmt_points(diff["max_drawdown"]),
        ),
        ("Exposure", fmt_pct(mine["exposure"]), fmt_pct(bench["exposure"]), ""),
    )
    ahead, windows = metrics["test_windows_ahead"], metrics["test_windows"]
    blocks: list[Block] = [
        Paragraph(
            "The test windows joined end to end: each one's equity is scaled to start "
            "where the previous one ended. The benchmark, "
            f"{bench['instrument']}'s {bench['method']}, is joined the same way over the "
            "same windows. Every window starts in cash and is measured from its first "
            "close, so the strategies and the benchmark both miss the move from one "
            "window's last close to the next one's first close."
        ),
        Table(("", "Out-of-sample", benchmark_name, "Difference"), rows),
        Paragraph(
            f"The strategies' total return beat the benchmark's in {ahead} of {windows} "
            "test windows."
        ),
        Paragraph(drawdown_sentence("The out-of-sample worst fall", mine["max_drawdown"])),
        Paragraph(drawdown_sentence("The benchmark's", bench["max_drawdown"])),
        Chart(
            "Out-of-sample equity",
            (
                equity_line("Out-of-sample", record.equity),
                equity_line(benchmark_name, record.benchmark),
            ),
            currency,
            log_scale=True,
        ),
        Chart(
            "Drawdown: fall from the highest close so far",
            (
                drawdown_line("Out-of-sample", record.equity),
                drawdown_line(benchmark_name, record.benchmark),
            ),
            "below peak",
            percent=True,
            shade=True,
        ),
        Paragraph("The equity chart's scale is logarithmic: equal heights are equal percentages."),
    ]
    return Section("Out of sample: the test windows joined", tuple(blocks))


def _fold_by_fold(record: WalkForwardRecord) -> Section:
    returns = tuple(
        (
            str(fold.number),
            _span(fold.train_run),
            fmt_pct(fold.train["strategy"]["cagr"]),
            fmt_points(fold.train["versus_benchmark"]["cagr"]),
            _span(fold.test_run),
            fmt_pct(fold.test["strategy"]["total_return"]),
            fmt_points(fold.test["versus_benchmark"]["total_return"]),
        )
        for fold in record.folds
    )
    risk = tuple(
        (
            str(fold.number),
            fmt_ratio(fold.train["strategy"]["sharpe"]),
            fmt_ratio(fold.train["benchmark"]["sharpe"]),
            fmt_ratio(fold.test["strategy"]["sharpe"]),
            fmt_ratio(fold.test["benchmark"]["sharpe"]),
            fmt_pct(depth_of(fold.train["strategy"])),
            fmt_pct(depth_of(fold.test["strategy"])),
            fmt_pct(depth_of(fold.test["benchmark"])),
        )
        for fold in record.folds
    )
    return Section(
        "Fold by fold: in-sample and out-of-sample",
        (
            Paragraph(
                "In-sample is the training window, out-of-sample the test window after "
                "it. Each window is a backtest of its own, measured against the benchmark "
                "over the same days. Training windows are compared by CAGR, because they "
                "differ in length; test windows by their total return. Differences are in "
                "percentage points."
            ),
            Table(
                (
                    "Fold",
                    "Training window",
                    "In-sample CAGR",
                    "vs benchmark",
                    "Test window",
                    "Out-of-sample return",
                    "vs benchmark",
                ),
                returns,
                numeric_from=2,
            ),
            Paragraph(
                "Risk in each window. A Sharpe ratio over one year of daily returns is "
                "noisy: read the column as a whole, not row by row."
            ),
            Table(
                (
                    "Fold",
                    "In-sample Sharpe",
                    "Benchmark",
                    "Out-of-sample Sharpe",
                    "Benchmark",
                    "In-sample max drawdown",
                    "Out-of-sample max drawdown",
                    "Benchmark",
                ),
                risk,
            ),
        ),
    )


def _trading(record: WalkForwardRecord) -> Section:
    currency = record.metrics["currency"]
    rows: list[tuple[str, ...]] = []
    fills = closed = wins = 0
    costs = Decimal(0)
    for fold in record.folds:
        trading = fold.test["trading"]
        fills += fold.test_run["outcome"]["fills"]
        closed += trading["closed_trades"]
        wins += trading["wins"]
        costs += Decimal(trading["costs"])
        rows.append(
            (
                str(fold.number),
                _span(fold.test_run),
                f"{fold.test_run['outcome']['fills']:,}",
                f"{trading['closed_trades']:,}",
                fmt_pct(trading["win_rate"]) if trading["win_rate"] is not None else "none closed",
                fmt_pct(fold.test["strategy"]["exposure"]),
                f"{fmt_amount(trading['costs'])} {currency}",
            )
        )
    win_rate = fmt_pct(Decimal(wins) / Decimal(closed)) if closed else "none closed"
    rows.append(("All", "", f"{fills:,}", f"{closed:,}", win_rate, "", f"{costs:,.2f} {currency}"))
    return Section(
        "Trading in the test windows",
        (
            Paragraph(
                "Each test window starts in cash, so it pays to enter its positions again: "
                "a strategy that holds for years, such as buy-and-hold, pays one entry a "
                "window that a single backtest pays once. Positions still open at the end "
                "of a window are not closed and are not counted as trades. Costs are "
                "commissions and regulatory fees; slippage is in each window's fills.csv."
            ),
            Table(
                (
                    "Fold",
                    "Test window",
                    "Fills",
                    "Closed trades",
                    "Win rate",
                    "Exposure",
                    "Commission and fees",
                ),
                tuple(rows),
                numeric_from=2,
            ),
        ),
    )


def _what_ran(record: WalkForwardRecord) -> Section:
    study = record.study
    code = study["code"]
    commit = code["git_commit"] or "unknown"
    version = f"{code['tyche_version']}, commit {commit[:12]}"
    if code["git_dirty"]:
        version += ", with uncommitted changes"
    rows = (
        ("Walk-forward", study["walk_forward_id"]),
        ("Started", study["started_at"]),
        ("Code", f"Tyche {version}; Python {code['python']}"),
        ("Config hash", study["config_hash"]),
        ("Market profile", study["market_profile"]),
        ("Range asked for", f"{study['range']['first']} to {study['range']['last']}"),
        ("Folds", study["scheme"]["described"]),
        ("Train step", study["train_step"]),
        ("Holdout", f"from {study['holdout_starts']}, never used"),
    )
    strategies = tuple(
        (s["id"], s["plugin"] or "", fmt_budget(s["budget"])) for s in study["strategies"]
    )
    records = tuple(
        (str(f["number"]), f["train"]["record"], f["test"]["record"]) for f in study["folds"]
    )
    return Section(
        "What ran",
        (
            Paragraph(
                "Everything needed to run this again: walk_forward.json in the same folder "
                "holds the full configuration, and each window's folder holds the full "
                "record of its backtest: run.json, metrics.json, equity.csv and fills.csv."
            ),
            Table(("", ""), rows),
            Table(("Strategy", "Plugin", "Budget"), strategies, numeric_from=2),
            Table(("Fold", "Training record", "Test record"), records, numeric_from=3),
        ),
    )


def _limits(record: WalkForwardRecord) -> Section:
    first = record.folds[0]
    walk_forward = (
        "Every window is a backtest of its own from the same starting cash. Joining the "
        "test windows compounds their returns, but each one traded the starting cash, "
        "not what the previous window had grown to.",
        "Strategies are warmed up on the history before each window, as in any backtest; "
        "the warm-up never trades.",
        "Training windows overlap whenever they are longer than a test window (anchored "
        "ones always do), so their results are not independent of each other.",
        "One test window a year gives few out-of-sample years. A strategy that trades a "
        "few times a year has few trades in each.",
    )
    return Section(
        "Data and its limits",
        (
            Paragraph(
                "Each window's run.json lists the history it read from the workspace's "
                "cache, with the data issues the audit found."
            ),
            Paragraph("Limits every result in this report shares:"),
            Bullets(data_limits(first.test_run["costs_checked_on"], record.metrics["currency"])),
            Paragraph("Limits a walk-forward adds:"),
            Bullets(walk_forward),
        ),
    )


def _span(run: dict[str, Any]) -> str:
    span = run["range"]
    return f"{span['first_session']} to {span['last_session']}"

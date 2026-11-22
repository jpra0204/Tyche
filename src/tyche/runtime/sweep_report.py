"""``report.html`` for a parameter sweep, built from its record alone (ADR-0030).

Like the other reports (ADR-0028), it reads only the record folder: ``sweep.json``,
``trials.json``, and the pick's full backtest record in ``pick/``. It never reads the
cache or runs anything.

Sections: the pick and how much to trust it (its deflated Sharpe ratio, with every
input, and the warnings); the pick against the benchmark, with its equity; every
trial; what ran; and the limits every result shares, with those a sweep adds.

Composition-root code (ADR-0004): it reads files and hands a ``Document`` to the HTML
renderer.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
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
from tyche.runtime.report import (
    REPORT_FILE,
    Record,
    ReportError,
    data_limits,
    depth_of,
    drawdown_line,
    equity_line,
    fmt_amount,
    fmt_budget,
    fmt_pct,
    fmt_points,
    fmt_ratio,
    read_record,
)
from tyche.runtime.sweep import PICK_FOLDER, SWEEP_FILE, SWEEP_FORMAT
from tyche.runtime.trials import TRIALS_FILE


@dataclass(frozen=True, slots=True)
class SweepRecord:
    """A sweep's record, read back.

    Attributes:
        folder: Where it is.
        study: ``sweep.json``.
        trials: ``trials.json``.
        pick: The pick's backtest record.
    """

    folder: Path
    study: dict[str, Any]
    trials: dict[str, Any]
    pick: Record


def is_sweep(folder: Path) -> bool:
    """True if ``folder`` holds a sweep's record."""
    return (folder / SWEEP_FILE).is_file()


def write_sweep_report(folder: Path) -> Path:
    """Write ``report.html`` into a sweep's folder, replacing any older one."""
    record = read_sweep(folder)
    path = folder / REPORT_FILE
    path.write_text(render_html(sweep_report(record)), encoding="utf-8")
    return path


def read_sweep(folder: Path) -> SweepRecord:
    """Read a sweep's folder, or raise ``ReportError`` saying what is wrong."""
    study = _json(folder / SWEEP_FILE, folder)
    trials = _json(folder / TRIALS_FILE, folder)
    for name, content in ((SWEEP_FILE, study), (TRIALS_FILE, trials)):
        if content.get("sweep_format") != SWEEP_FORMAT:
            raise ReportError(
                f"{folder}: {name} is format {content.get('sweep_format')}, "
                f"this version of Tyche reads format {SWEEP_FORMAT}"
            )
    if trials.get("pick") is None:
        raise ReportError(f"{folder}: no trial had a Sharpe ratio, so nothing was picked")
    return SweepRecord(folder, study, trials, read_record(folder / PICK_FOLDER))


def _json(path: Path, folder: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReportError(f"{folder}: {path.name} is missing")
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


# --- the document ---------------------------------------------------------------------


def sweep_report(record: SweepRecord) -> Document:
    """The report's content, as a document the renderer can draw."""
    study, trials = record.study, record.trials
    span = study["range"]
    grid = trials["grid"]
    subtitle = (
        f"{span['first']} to {span['last']}: {len(trials['trials'])} combinations of "
        f"{trials['strategy']} ({trials['plugin']}), each a backtest from "
        f"{fmt_amount(study['starting_cash']['amount'])} {study['starting_cash']['currency']}. "
        f"Swept: {', '.join(grid)}."
    )
    callouts = [
        Callout(
            "Every figure here is in-sample: the pick was chosen on the same days it is "
            "measured on, so it is the best of these trials over this history, not a "
            "forecast. For an out-of-sample result, run a walk-forward with this sweep: "
            "each fold picks on its training window and tests the pick on the years after."
        ),
        _verdict(trials),
    ]
    callouts.extend(Callout(w, Tone.WARNING) for w in trials["warnings"])
    if study["code"]["git_dirty"]:
        callouts.append(
            Callout(
                "The code had uncommitted changes, so its commit alone does not reproduce "
                "this sweep.",
                Tone.WARNING,
            )
        )
    return Document(
        title=f"Sweep {study['sweep_id']}",
        subtitle=subtitle,
        callouts=tuple(callouts),
        sections=(
            _deflated(trials),
            _the_pick(record),
            _every_trial(trials),
            _what_ran(record),
            _limits(record),
        ),
    )


def _verdict(trials: dict[str, Any]) -> Callout:
    deflated = trials["deflated_sharpe"]
    if deflated is None:
        return Callout(
            f"The pick's Sharpe ratio could not be deflated: {trials['deflation_error']}.",
            Tone.WARNING,
        )
    chance = fmt_pct(deflated["probability"])
    counted = trials["trials_counted"]["total"]
    if deflated["significant"]:
        return Callout(
            f"After {counted} trials, the chance that the pick's true Sharpe ratio is above "
            f"zero is {chance}: significant at {fmt_pct(deflated['confidence'])}. That says "
            "the pick is unlikely to be pure luck; it does not say it beats the benchmark."
        )
    return Callout(
        f"After {counted} trials, the chance that the pick's true Sharpe ratio is above "
        f"zero is {chance}, below {fmt_pct(deflated['confidence'])}.",
        Tone.WARNING,
    )


def _deflated(trials: dict[str, Any]) -> Section:
    counted = trials["trials_counted"]
    deflated = trials["deflated_sharpe"]
    blocks: list[Block] = [
        Paragraph(
            "The best of many tries looks better than it is, even when none of them has an "
            "edge. The deflated Sharpe ratio (Bailey and López de Prado, 2014) is the "
            "chance that the pick's true Sharpe ratio is above zero, once the number of "
            "trials behind it, how much their results varied, the length of the history "
            "and the shape of the pick's daily returns are taken into account."
        ),
        Paragraph(
            f"Trials counted: {counted['total']}. This grid holds {counted['this_grid']}; "
            f"{counted['recorded_before']} distinct trials of {trials['plugin']} were "
            "already recorded in this workspace (backtests, walk-forwards and earlier "
            "sweeps), and those this grid repeats are counted once. Every distinct set of "
            "parameters ever run counts, because each one seen shaped what was tried next."
        ),
    ]
    if deflated is None:
        blocks.append(Paragraph(f"Not computed: {trials['deflation_error']}."))
        return Section("How much to trust the pick", tuple(blocks))
    rows = (
        ("Deflated Sharpe ratio", fmt_pct(deflated["probability"])),
        ("Pick's Sharpe ratio, annualised", fmt_ratio(deflated["sharpe_annualised"])),
        (
            "Sharpe ratio the best of the trials reaches by luck, annualised",
            fmt_ratio(deflated["threshold_annualised"]),
        ),
        ("Trials counted (N)", str(deflated["trials"])),
        (
            "Variance of this sweep's Sharpe ratios, per session (V)",
            deflated["variance_of_sharpes"],
        ),
        ("Daily returns (T)", f"{deflated['returns']:,}"),
        ("Skewness of the pick's daily returns", deflated["skewness"]),
        ("Kurtosis of the pick's daily returns (3 if normal)", deflated["kurtosis"]),
    )
    blocks += [
        Table(("", ""), rows),
        Paragraph(
            "The variance is taken over this sweep's trials only, because they are the "
            "ones measured over the same days as the pick. The more the trials' results "
            "differ, and the more trials there are, the higher the Sharpe ratio luck alone "
            "is expected to reach. Negative skewness and fat tails (kurtosis above 3) make "
            "a Sharpe ratio less reliable, and lower the result further."
        ),
    ]
    return Section("How much to trust the pick", tuple(blocks))


def _the_pick(record: SweepRecord) -> Section:
    trials, metrics = record.trials, record.pick.metrics
    picked = trials["pick"]
    mine, bench, diff = metrics["strategy"], metrics["benchmark"], metrics["versus_benchmark"]
    currency = metrics["currency"]
    benchmark_name = f"{bench['instrument']} total return"
    parameters = tuple((name, _shown(value)) for name, value in picked["parameters"].items())
    rows = (
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
            "Max drawdown",
            fmt_pct(depth_of(mine)),
            fmt_pct(depth_of(bench)),
            fmt_points(diff["max_drawdown"]),
        ),
        ("Exposure", fmt_pct(mine["exposure"]), fmt_pct(bench["exposure"]), ""),
        (
            "Final equity",
            f"{fmt_amount(mine['end_equity'])} {currency}",
            f"{fmt_amount(bench['end_equity'])} {currency}",
            "",
        ),
    )
    return Section(
        f"The pick: trial {picked['number']}",
        (
            Paragraph(f"Chosen by {trials['rule']}. Its swept parameters:"),
            Table(("Parameter", "Value"), parameters),
            Paragraph(
                "Every configured strategy ran together, as in any backtest; only the "
                f"swept one, {trials['strategy']}, changed between trials. The pick's full "
                f"record is in {PICK_FOLDER}/."
            ),
            Table(("", "Pick", benchmark_name, "Difference"), rows),
            Chart(
                "The pick's equity",
                (
                    equity_line("Pick", record.pick.equity),
                    equity_line(benchmark_name, record.pick.benchmark),
                ),
                currency,
                log_scale=True,
            ),
            Chart(
                "Drawdown: fall from the highest close so far",
                (
                    drawdown_line("Pick", record.pick.equity),
                    drawdown_line(benchmark_name, record.pick.benchmark),
                ),
                "below peak",
                percent=True,
                shade=True,
            ),
        ),
    )


def _every_trial(trials: dict[str, Any]) -> Section:
    names = tuple(trials["grid"])
    picked = trials["pick"]["number"]
    rows: list[tuple[str, ...]] = []
    for trial in trials["trials"]:
        values = tuple(_shown(trial["parameters"][name]) for name in names)
        mark = f"{trial['number']} (pick)" if trial["number"] == picked else str(trial["number"])
        if not trial["measured"]:
            rows.append((mark, *values, trial["failure"], "", "", "", ""))
            continue
        rows.append(
            (
                mark,
                *values,
                fmt_ratio(trial["sharpe"]),
                fmt_pct(trial["cagr"]),
                fmt_pct(trial["max_drawdown"]),
                f"{trial['closed_trades']:,}",
                fmt_points(trial["versus_benchmark"]["cagr"]),
            )
        )
    measured = [Decimal(t["sharpe"]) for t in trials["trials"] if t.get("sharpe") is not None]
    above = sum(1 for s in measured if s > 0)
    bench = trials["benchmark"]
    summary = (
        f"{above} of {len(measured)} measured trials have a Sharpe ratio above zero. "
        f"The benchmark's over the same days is {fmt_ratio(bench['sharpe'])}, with a CAGR "
        f"of {fmt_pct(bench['cagr'])}."
        if bench is not None
        else f"{above} of {len(measured)} measured trials have a Sharpe ratio above zero."
    )
    return Section(
        "Every trial",
        (
            Paragraph(
                "In the grid's order, the last parameter changing fastest. Read the table "
                "as a landscape: a pick whose neighbours do nearly as well is more "
                "believable than a lone peak."
            ),
            Paragraph(summary),
            Table(
                ("Trial", *names, "Sharpe", "CAGR", "Max drawdown", "Closed trades", "CAGR vs bm"),
                tuple(rows),
                numeric_from=len(names) + 1,
            ),
        ),
    )


def _what_ran(record: SweepRecord) -> Section:
    study, trials = record.study, record.trials
    code = study["code"]
    commit = code["git_commit"] or "unknown"
    version = f"{code['tyche_version']}, commit {commit[:12]}"
    if code["git_dirty"]:
        version += ", with uncommitted changes"
    rows = (
        ("Sweep", study["sweep_id"]),
        ("Started", study["started_at"]),
        ("Code", f"Tyche {version}; Python {code['python']}"),
        ("Config hash", study["config_hash"]),
        ("Sweep file", f"{study['sweep']['file']} ({study['sweep']['hash']})"),
        ("Market profile", study["market_profile"]),
        ("Range", f"{study['range']['first']} to {study['range']['last']}"),
        ("Pick rule", trials["rule"]),
        ("Holdout", f"from {study['holdout_starts']}, never used"),
    )
    strategies = tuple(
        (s["id"], s["plugin"] or "", fmt_budget(s["budget"])) for s in study["strategies"]
    )
    grid = tuple(
        (name, ", ".join(_shown(v) for v in values)) for name, values in trials["grid"].items()
    )
    return Section(
        "What ran",
        (
            Paragraph(
                "Everything needed to run this again: sweep.json holds the full "
                "configuration and the sweep file, and trials.json every trial's "
                "parameters. Only the pick kept its equity and fills; any other trial can "
                "be run again as a backtest with its parameters in the strategy file."
            ),
            Table(("", ""), rows),
            Table(("Strategy", "Plugin", "Budget"), strategies, numeric_from=2),
            Table(("Swept parameter", "Values tried"), grid),
        ),
    )


def _limits(record: SweepRecord) -> Section:
    sweep = (
        "The pick is the best of these trials on this history. Some of its lead over the "
        "others is luck, which the deflated Sharpe ratio estimates but cannot remove.",
        "The trials are not independent: neighbouring parameters trade alike. The "
        "deflated Sharpe ratio treats each as independent, which overstates the number of "
        "really different tries and makes the discount somewhat harsher.",
        "The trial count holds only what is recorded in this workspace. Ideas tried "
        "elsewhere, or read about, are not counted.",
        "A grid's edges are a choice: the best value may lie beyond them.",
    )
    return Section(
        "Data and its limits",
        (
            Paragraph(
                "The pick's run.json lists the history it read from the workspace's cache, "
                "with the data issues the audit found. Every trial read the same history."
            ),
            Paragraph("Limits every result in this report shares:"),
            Bullets(
                data_limits(record.pick.run["costs_checked_on"], record.pick.metrics["currency"])
            ),
            Paragraph("Limits a sweep adds:"),
            Bullets(sweep),
        ),
    )


def _shown(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)

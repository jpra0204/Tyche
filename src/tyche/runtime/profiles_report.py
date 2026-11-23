"""``report.html`` for a risk-profile comparison, built from its record alone (ADR-0036).

It reads only the comparison's folder: ``profiles.json`` and each profile's backtest
record under ``runs/<profile>/``. It never reads the cache or runs anything.

Sections: every profile side by side against the benchmark; what each profile's
limits did (cuts, daily loss triggers, the drawdown halt); what ran; and the limits
every result shares. It names no best profile: which one to trade is Pablo's choice.

Composition-root code (ADR-0004): it reads files and hands a ``Document`` to the HTML
renderer.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche.adapters.reports import (
    Block,
    Bullets,
    Callout,
    Chart,
    Document,
    Line,
    Mark,
    Paragraph,
    Section,
    Table,
    Tone,
    render_html,
)
from tyche.core.domain import ORDER_RULES
from tyche.runtime.profiles import PROFILES_FILE, PROFILES_FORMAT
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
    fmt_day,
    fmt_pct,
    fmt_ratio,
    halt_of,
    read_record,
)

PROFILE_COLOURS = ("#1f5fa8", "#c0392b", "#2e8b57", "#8e44ad", "#d35400", "#16a085")
"""One colour per profile, in the comparison's order; the benchmark is grey."""

BENCHMARK_COLOUR = "#8c8c8c"


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """One profile of the comparison, read back: its entry in ``profiles.json`` and,
    when its run was measured, the run's record."""

    entry: dict[str, Any]
    record: Record | None

    @property
    def name(self) -> str:
        return str(self.entry["name"])


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    """A comparison's record, read back."""

    folder: Path
    study: dict[str, Any]
    profiles: tuple[ProfileResult, ...]


def write_profiles_report(folder: Path) -> Path:
    """Write ``report.html`` into a comparison's folder, replacing any older one."""
    document = profiles_report(read_comparison(folder))
    path = folder / REPORT_FILE
    path.write_text(render_html(document), encoding="utf-8")
    return path


def read_comparison(folder: Path) -> ComparisonRecord:
    """Read a comparison's folder, or raise ``ReportError`` saying what is wrong."""
    path = folder / PROFILES_FILE
    if not path.is_file():
        raise ReportError(f"{folder}: is not a risk-profile comparison: {PROFILES_FILE} is missing")
    study: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if study.get("profiles_format") != PROFILES_FORMAT:
        raise ReportError(
            f"{folder}: {PROFILES_FILE} is format {study.get('profiles_format')}, "
            f"this version of Tyche reads format {PROFILES_FORMAT}"
        )
    profiles: list[ProfileResult] = []
    for entry in study["profiles"]:
        run = entry["run"]
        record = read_record(folder / run["folder"]) if run and run["measured"] else None
        profiles.append(ProfileResult(entry, record))
    if not any(p.record is not None for p in profiles):
        raise ReportError(
            f"{folder}: no profile's run was measured, so there is nothing to compare"
        )
    return ComparisonRecord(folder, study, tuple(profiles))


# --- the document ---------------------------------------------------------------------


def profiles_report(comparison: ComparisonRecord) -> Document:
    """The report's content, as a document the renderer can draw."""
    study = comparison.study
    span = study["range"]
    starting = study["starting_cash"]
    names = ", ".join(p.name for p in comparison.profiles)
    strategies = ", ".join(f"{s['id']} ({fmt_budget(s['budget'])})" for s in study["strategies"])
    subtitle = (
        f"{span['first']} to {span['last']}. Risk profiles: {names}. Strategies: {strategies}. "
        f"Starting cash {fmt_amount(starting['amount'])} {starting['currency']}."
    )
    count = len(comparison.profiles)
    callouts = [
        Callout(
            "One backtest per profile, over the same days: in-sample results, not a verdict. "
            "This report names no best profile."
        ),
        Callout(
            f"{count} profiles were compared. Choosing the one that looks best here is a "
            "selection, like picking from a sweep, and the more profiles you try the more "
            "the best of them flatters itself. A comparison adds no trial to any "
            "strategy's count, so nothing here corrects for it. Choose a profile for the "
            "account you will trade and the losses you can sit through, not for the "
            "highest number.",
            Tone.WARNING,
        ),
    ]
    if study["code"]["git_dirty"]:
        callouts.append(
            Callout(
                "The code had uncommitted changes, so its commit alone does not reproduce "
                "these runs.",
                Tone.WARNING,
            )
        )
    if not study["outcome"]["completed"]:
        callouts.append(
            Callout(f"The comparison stopped: {study['outcome']['failure']}", Tone.WARNING)
        )
    for profile in comparison.profiles:
        callout = _profile_callout(profile)
        if callout is not None:
            callouts.append(callout)
    return Document(
        title=f"Risk profiles {study['comparison_id']}",
        subtitle=subtitle,
        callouts=tuple(callouts),
        sections=(
            _side_by_side(comparison),
            _what_the_limits_did(comparison),
            _what_ran(comparison),
            _limits(comparison),
        ),
    )


def _profile_callout(profile: ProfileResult) -> Callout | None:
    run = profile.entry["run"]
    if run is None:
        return Callout(f"{profile.name} did not run: the comparison stopped first.", Tone.WARNING)
    if not run["completed"]:
        return Callout(f"{profile.name}'s run halted: {run['failure']}", Tone.WARNING)
    if not run["measured"]:
        return Callout(
            f"{profile.name}'s run could not be measured: {run['metrics_error']}", Tone.WARNING
        )
    assert profile.record is not None
    halt = halt_of(profile.record.run)
    if halt is None:
        return None
    return Callout(
        f"The drawdown kill halted {profile.name} on {fmt_day(halt['at'])}, "
        f"{fmt_pct(halt['drawdown'])} below its peak, with "
        f"{fmt_pct(halted_share(profile.record, halt))} of the range still to run. After "
        "that its run sent no order and held what it held to the end, so its results from "
        "then on are those of not trading, not of the strategies.",
        Tone.WARNING,
    )


def halted_share(record: Record, halt: dict[str, Any]) -> Decimal:
    """The share of the run's closes after the halt's close."""
    at = datetime.fromisoformat(halt["at"]).astimezone(UTC)
    after = sum(1 for point in record.equity if point.at > at)
    return Decimal(after) / Decimal(len(record.equity))


def _measured(comparison: ComparisonRecord) -> list[tuple[ProfileResult, Record]]:
    return [(p, p.record) for p in comparison.profiles if p.record is not None]


def _side_by_side(comparison: ComparisonRecord) -> Section:
    measured = _measured(comparison)
    first = measured[0][1]
    bench = first.metrics["benchmark"]
    benchmark_name = f"{bench['instrument']} total return"
    currency = first.metrics["currency"]

    def cells(series: dict[str, Any]) -> tuple[str, ...]:
        return (
            f"{fmt_amount(series['end_equity'])} {currency}",
            fmt_pct(series["total_return"]),
            fmt_pct(series["cagr"]),
            fmt_pct(series["volatility"]),
            fmt_ratio(series["sharpe"]),
            fmt_ratio(series["sortino"]),
            fmt_pct(depth_of(series)),
            fmt_pct(series["exposure"]),
        )

    labels = (
        "Final equity",
        "Total return",
        "CAGR",
        "Volatility",
        "Sharpe (rf 0)",
        "Sortino (rf 0)",
        "Max drawdown",
        "Exposure",
    )
    columns = [cells(record.metrics["strategy"]) for _, record in measured] + [cells(bench)]
    rows: list[tuple[str, ...]] = [
        (label, *(column[n] for column in columns)) for n, label in enumerate(labels)
    ]
    rows.append(
        (
            "Costs",
            *(f"{fmt_amount(r.metrics['trading']['costs'])} {currency}" for _, r in measured),
            "",
        )
    )
    rows.append(
        ("Closed trades", *(f"{r.metrics['trading']['closed_trades']:,}" for _, r in measured), "")
    )

    colours = {
        p.name: PROFILE_COLOURS[n % len(PROFILE_COLOURS)] for n, (p, _) in enumerate(measured)
    }
    halted: dict[datetime, list[str]] = {}
    for p, record in measured:
        halt = halt_of(record.run)
        if halt is not None:
            at = datetime.fromisoformat(halt["at"]).astimezone(UTC)
            halted.setdefault(at, []).append(p.name)
    marks = tuple(Mark(at, f"{', '.join(names)} halted") for at, names in sorted(halted.items()))
    equity = tuple(
        Line(p.name, equity_line(p.name, r.equity).points, colours[p.name]) for p, r in measured
    )
    drawdown = tuple(
        Line(p.name, drawdown_line(p.name, r.equity).points, colours[p.name]) for p, r in measured
    )
    blocks: list[Block] = [
        Paragraph(
            "The same strategies, with the same parameters, over the same days, once under "
            "each risk profile, against the benchmark measured the same way. Only the risk "
            "limits differ. Sharpe and Sortino use a risk-free rate of zero."
        ),
        Table(("", *(p.name for p, _ in measured), benchmark_name), tuple(rows)),
        Chart(
            "Equity",
            (
                *equity,
                Line(benchmark_name, equity_line("", first.benchmark).points, BENCHMARK_COLOUR),
            ),
            currency,
            log_scale=True,
            marks=marks,
        ),
        Chart(
            "Drawdown: fall from the highest close so far",
            (
                *drawdown,
                Line(benchmark_name, drawdown_line("", first.benchmark).points, BENCHMARK_COLOUR),
            ),
            "below peak",
            percent=True,
            marks=marks,
        ),
        Paragraph("The equity chart's scale is logarithmic: equal heights are equal percentages."),
    ]
    return Section("Side by side", tuple(blocks))


def _what_the_limits_did(comparison: ComparisonRecord) -> Section:
    rows: list[tuple[str, ...]] = []
    for profile in comparison.profiles:
        risk = profile.entry["risk"]
        limits = (
            f"{fmt_pct(risk['risk_per_trade'])} a trade; {risk['max_open_positions']} "
            f"positions of at most {fmt_pct(risk['max_position_size'])}; daily loss "
            f"{fmt_pct(risk['daily_loss_limit'])}; kill at {fmt_pct(risk['drawdown_kill'])}"
        )
        if profile.record is None:
            rows.append((profile.name, limits, "not measured", "", ""))
            continue
        outcome = profile.record.run["outcome"]
        cut = outcome.get("risk_adjustments", {})
        orders = sum(n for key, n in cut.items() if key.split(".")[0] in ORDER_RULES)
        gate = {k: n for k, n in cut.items() if k.split(".")[0] not in ORDER_RULES}
        shrunk = sum(n for key, n in gate.items() if key.endswith(".shrink"))
        blocked = sum(n for key, n in gate.items() if key.endswith(".block"))
        rules = outcome.get("account_rules") or {"daily_loss_limit_triggers": 0, "halt": None}
        halt = rules["halt"]
        rows.append(
            (
                profile.name,
                limits,
                f"{shrunk:,} shrunk, {blocked:,} blocked"
                + (f"; {orders:,} purchases capped" if orders else ""),
                f"{rules['daily_loss_limit_triggers']:,}",
                (
                    f"{fmt_day(halt['at'])} ({fmt_pct(halted_share(profile.record, halt))} "
                    "of the range left)"
                )
                if halt
                else "never",
            )
        )
    return Section(
        "What each profile's limits did",
        (
            Paragraph(
                "Each profile's limits, and how often they changed what the strategies "
                "asked for: contributions the risk gate shrank or blocked, sessions after "
                "which the daily loss limit allowed no entry or addition, and the day the "
                "drawdown kill halted trading, if it did."
            ),
            Table(
                ("Profile", "Limits", "Gate cuts", "Daily loss limit hit", "Halted on"),
                tuple(rows),
            ),
        ),
    )


def _what_ran(comparison: ComparisonRecord) -> Section:
    study = comparison.study
    code = study["code"]
    rows = [
        ("Comparison", study["comparison_id"]),
        ("Code", f"Tyche {code['tyche_version']}, commit {code['git_commit']}"),
        ("Market profile", study["market_profile"]),
        ("Range", f"{study['range']['first']} to {study['range']['last']}"),
        ("Holdout starts", study["holdout_starts"]),
        ("Trials added", "none: each profile ran the strategies' configured parameters"),
    ]
    hashes = tuple(
        (
            p.name,
            p.entry["config_hash"],
            p.entry["run"]["run_id"] if p.entry["run"] else "not run",
        )
        for p in comparison.profiles
    )
    return Section(
        "What ran",
        (
            Paragraph(
                "Each profile's run is a full backtest record in runs/<profile>/ of this "
                "folder. Its config hash covers the guardrails and that profile only, so "
                "each profile's hash differs."
            ),
            Table(("", ""), tuple(rows)),
            Table(("Profile", "Config hash", "Run"), hashes),
        ),
    )


def _limits(comparison: ComparisonRecord) -> Section:
    first = _measured(comparison)[0][1]
    limits = (
        *data_limits(first.run["costs_checked_on"], first.metrics["currency"]),
        "Everything here is in-sample: one run per profile over one stretch of history.",
        "Research backtests keep their own starting cash, so the guardrails' money caps "
        "are not applied; tyche capital shows what a smaller account does.",
    )
    return Section(
        "Data and its limits",
        (
            Paragraph("Every profile read the same history and shares these limits."),
            Bullets(limits),
        ),
    )

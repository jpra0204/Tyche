"""``report.html`` for a capital analysis, built from its record alone (ADR-0031).

Like the other reports (ADR-0028), it reads only the record folder: ``capital.json``.
It never reads the cache or runs anything.

Sections: the answer for each strategy and plan; every amount, strategy by strategy;
what one round trip costs per position; today's share prices; what ran; and the
limits every result shares, with those this analysis adds.

Composition-root code (ADR-0004): it reads files and hands a ``Document`` to the HTML
renderer.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche.adapters.reports import (
    Block,
    Bullets,
    Callout,
    Document,
    Paragraph,
    Section,
    Table,
    Tone,
    render_html,
)
from tyche.runtime.capital import CAPITAL_FORMAT, FIXED, TIERED
from tyche.runtime.report import (
    REPORT_FILE,
    ReportError,
    data_limits,
    fmt_amount,
    fmt_pct,
    fmt_points,
    fmt_ratio,
)
from tyche.runtime.trials import CAPITAL_FILE

PLAN_NAMES = {FIXED: "IBKR Pro Fixed", TIERED: "IBKR Pro Tiered"}


def is_capital(folder: Path) -> bool:
    """True if ``folder`` holds a capital analysis's record."""
    return (folder / CAPITAL_FILE).is_file()


def write_capital_report(folder: Path) -> Path:
    """Write ``report.html`` into a capital analysis's folder, replacing any older one."""
    record = read_capital(folder)
    path = folder / REPORT_FILE
    path.write_text(render_html(capital_report(record)), encoding="utf-8")
    return path


def read_capital(folder: Path) -> dict[str, Any]:
    """Read ``capital.json``, or raise ``ReportError`` saying what is wrong."""
    path = folder / CAPITAL_FILE
    if not path.is_file():
        raise ReportError(f"{folder}: {CAPITAL_FILE} is missing")
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ReportError(f"{path}: not valid JSON: {error}") from None
    if record.get("capital_format") != CAPITAL_FORMAT:
        raise ReportError(
            f"{folder}: {CAPITAL_FILE} is format {record.get('capital_format')}, "
            f"this version of Tyche reads format {CAPITAL_FORMAT}"
        )
    return record


# --- the document ---------------------------------------------------------------------


def capital_report(record: dict[str, Any]) -> Document:
    """The report's content, as a document the renderer can draw."""
    request, span, currency = record["request"], record["range"], record["currency"]
    plans = ", ".join(PLAN_NAMES.get(p, p) for p in record["plans"])
    subtitle = (
        f"{span['first']} to {span['last']}: each strategy alone, with the whole account, "
        f"at {len(request['amounts'])} account sizes from "
        f"{_amount(request['amounts'][0], currency)} to "
        f"{_amount(request['amounts'][-1], currency)}, against a "
        f"{_amount(request['reference'], currency)} reference account. Plans: {plans}."
    )
    callouts = [
        Callout(
            "An amount is viable when its CAGR after costs is within "
            f"{fmt_points(request['tolerance']).lstrip('+')} a year of the reference "
            "account's, either way, under the same plan: a small account that does much "
            "better than the large one is running a different strategy, by luck in when "
            "it could afford a share. The minimum viable capital is the smallest amount "
            "from which every larger amount tested is viable. It says what account "
            "size costs a strategy; whether the strategy has an edge worth keeping is "
            "whether it beats the benchmark, shown beside it."
        ),
        *_verdicts(record),
    ]
    if record["code"]["git_dirty"]:
        callouts.append(
            Callout(
                "The code had uncommitted changes, so its commit alone does not reproduce "
                "this analysis.",
                Tone.WARNING,
            )
        )
    return Document(
        title=f"Capital {record['capital_id']}",
        subtitle=subtitle,
        callouts=tuple(callouts),
        sections=(
            _answers(record),
            *(_strategy(record, study) for study in record["strategies"]),
            _round_trips(record),
            _today(record),
            _what_ran(record),
            _limits(record),
        ),
    )


def _verdicts(record: dict[str, Any]) -> list[Callout]:
    currency = record["currency"]
    benchmark = record["benchmark"]
    found: list[Callout] = []
    for study in record["strategies"]:
        for plan in study["plans"]:
            name = f"{study['id']} under {PLAN_NAMES.get(plan['plan'], plan['plan'])}"
            reference = plan["reference"]
            if not reference["measured"]:
                found.append(
                    Callout(
                        f"{name}: the reference run was not measured "
                        f"({reference['failure']}), so no amount can be judged.",
                        Tone.WARNING,
                    )
                )
                continue
            if plan.get("reference_too_large"):
                found.append(
                    Callout(
                        f"{name}: the reference account is too large for this strategy. The "
                        f"cap on a bar's volume cut {reference['cut_short']:,} of its orders "
                        "short, so its result is not the strategy free of its size, and no "
                        "verdict below can be trusted. Run again with a smaller --reference.",
                        Tone.WARNING,
                    )
                )
                continue
            minimum = plan["minimum_viable"]
            if minimum is None:
                text = f"{name}: no amount tested is viable; more capital is needed."
            else:
                text = f"{name}: viable from {_amount(minimum, currency)}."
            edge = reference["versus_benchmark"]
            sharpe = Decimal(edge["sharpe"]) if edge["sharpe"] is not None else None
            cagr = Decimal(edge["cagr"]) if edge["cagr"] is not None else None
            if benchmark is None:
                found.append(Callout(text, Tone.WARNING if minimum is None else Tone.NOTE))
                continue
            text += (
                f" On the reference account: {fmt_pct(reference['cagr'])} a year with a "
                f"Sharpe ratio of {fmt_ratio(reference['sharpe'])}, against "
                f"{benchmark['instrument']}'s {fmt_pct(benchmark['cagr'])} and "
                f"{fmt_ratio(benchmark['sharpe'])}."
            )
            if sharpe is not None and sharpe <= 0:
                text += " It does not beat the benchmark even there: there is no edge to keep."
            elif cagr is not None and cagr < 0:
                text += (
                    " A higher Sharpe ratio with a lower return is a smaller, steadier "
                    "result, not yet an edge: check it out of sample (tyche walk-forward)."
                )
            weak = minimum is None or (sharpe is not None and sharpe <= 0)
            found.append(Callout(text, Tone.WARNING if weak else Tone.NOTE))
    return found


def _answers(record: dict[str, Any]) -> Section:
    currency = record["currency"]
    rows: list[tuple[str, ...]] = []
    for study in record["strategies"]:
        for plan in study["plans"]:
            reference = plan["reference"]
            at = next(
                (r for r in plan["runs"] if r["amount"] == plan["minimum_viable"]),
                None,
            )
            rows.append(
                (
                    study["id"],
                    PLAN_NAMES.get(plan["plan"], plan["plan"]),
                    "not judged: reference too large"
                    if plan.get("reference_too_large")
                    else _amount(plan["minimum_viable"], currency)
                    if plan["minimum_viable"] is not None
                    else "none tested",
                    fmt_pct(reference.get("cagr")),
                    fmt_ratio(reference.get("sharpe")),
                    fmt_pct(at.get("cagr")) if at is not None else "",
                    fmt_points(at["versus_benchmark"]["cagr"]) if at and at["measured"] else "",
                )
            )
    benchmark = record["benchmark"]
    blocks: list[Block] = [
        Table(
            (
                "Strategy",
                "Plan",
                "Minimum viable",
                "Reference CAGR",
                "Reference Sharpe",
                "CAGR at minimum",
                "vs benchmark",
            ),
            tuple(rows),
            numeric_from=2,
        )
    ]
    if benchmark is not None:
        blocks.append(
            Paragraph(
                f"The benchmark, {benchmark['instrument']}'s total return over the same days "
                f"({benchmark['method']}), has a CAGR of {fmt_pct(benchmark['cagr'])} and "
                f"a Sharpe ratio of {fmt_ratio(benchmark['sharpe'])} at every account size."
            )
        )
    return Section("The answer", tuple(blocks))


def _strategy(record: dict[str, Any], study: dict[str, Any]) -> Section:
    currency = record["currency"]
    blocks: list[Block] = [
        Paragraph(
            f"Plugin {study['plugin']} {study['version']}, with its configured parameters: "
            f"{_parameters(study['parameters'])}."
        )
    ]
    for plan in study["plans"]:
        rows = [_run_row(run, currency) for run in plan["runs"]]
        rows.append(_run_row(plan["reference"], currency, reference=True))
        blocks += [
            Paragraph(PLAN_NAMES.get(plan["plan"], plan["plan"])),
            Table(
                (
                    "Starting cash",
                    "CAGR",
                    "Size penalty",
                    "Viable",
                    "Costs a year",
                    "Cost drag",
                    "Sharpe",
                    "Exposure",
                    "Short of a share",
                    "Cut short",
                    "vs benchmark",
                ),
                tuple(rows),
            ),
        ]
    blocks.append(
        Paragraph(
            "Size penalty: the reference account's CAGR minus this one's; negative when "
            "this one did better. Costs a year: "
            "commission, fees and slippage as a share of the average equity. Cost drag: "
            "CAGR before costs minus after. Short of a share: decisions at which some "
            "target was worth less than one whole share, so the strategy held less than it "
            "decided. Cut short: orders that expired partly unfilled because the "
            "simulator fills at most 1% of a bar's volume; any on the reference account "
            "make it too large to be the reference. Exposure: the average share of equity "
            "invested; cash left over by whole shares lowers it."
        )
    )
    return Section(study["id"], tuple(blocks))


def _run_row(run: dict[str, Any], currency: str, *, reference: bool = False) -> tuple[str, ...]:
    amount = _amount(run["amount"], currency) + (" (reference)" if reference else "")
    if not run["measured"]:
        return (amount, run["failure"] or "not measured", "", "", "", "", "", "", "", "", "")
    viable = "" if reference else ("yes" if run["viable"] else "no")
    return (
        amount,
        fmt_pct(run["cagr"]),
        "" if reference else fmt_points(run["size_penalty"]),
        viable,
        fmt_pct(run["costs_per_year"]),
        fmt_points(run["cagr_drag"]),
        fmt_ratio(run["sharpe"]),
        fmt_pct(run["exposure"]),
        f"{run['short_of_a_share']:,} of {run['decisions']:,}",
        f"{run.get('cut_short', 0):,}",
        fmt_points(run["versus_benchmark"]["cagr"]),
    )


def _round_trips(record: dict[str, Any]) -> Section:
    currency = record["currency"]
    trips = record["round_trips"]
    positions = record["request"]["positions"]
    blocks: list[Block] = [
        Paragraph(
            "Arithmetic, not a backtest: what buying one position and selling it again "
            "costs, as a share of the position, when the account is split into equal "
            f"positions, at {_amount(trips['price'], currency)} a share. Commission, "
            "fees and slippage on both orders. A strategy that turns each position over "
            "once a month pays twelve of these a year."
        )
    ]
    for plan, rows in trips["plans"].items():
        blocks += [
            Paragraph(PLAN_NAMES.get(plan, plan)),
            Table(
                (
                    "Account",
                    *(f"{n} position{'s' if n > 1 else ''}" for n in range(1, positions + 1)),
                ),
                tuple(
                    (
                        _amount(row["amount"], currency),
                        *(
                            fmt_pct(row["by_positions"][str(n)])
                            if row["by_positions"][str(n)] is not None
                            else "no share"
                            for n in range(1, positions + 1)
                        ),
                    )
                    for row in rows
                ),
            ),
        ]
    return Section("What one round trip costs", tuple(blocks))


def _today(record: dict[str, Any]) -> Section:
    currency = record["currency"]
    today = record["today"]
    amounts = record["request"]["amounts"]
    positions = today["positions"]
    rows: list[tuple[str, ...]] = []
    for candidate in today["candidates"]:
        if candidate["close"] is None:
            rows.append((candidate["instrument"], "not cached", "", *("" for _ in amounts)))
            continue
        rows.append(
            (
                candidate["instrument"],
                candidate["day"],
                fmt_amount(candidate["close"]),
                *(str(candidate["shares"][a]) for a in amounts),
            )
        )
    return Section(
        "Today's share prices",
        (
            Paragraph(
                "The backtests trade at past prices. Most of these ETFs have never split, so "
                "their shares cost more now than over most of the history tested, and "
                "whole shares bind harder today than the backtests show. This table reads "
                "each candidate's latest cached close, which may lie inside the holdout; "
                "only the price is read, nothing is run on it (ADR-0031)."
            ),
            Paragraph(
                f"Each cell: the whole shares one of {positions} equal positions buys, costs "
                "included, under the plan backtests use. Zero means that ETF cannot be "
                "held at all at that account size."
            ),
            Table(
                ("Candidate", "Close of", "Close", *(_amount(a, currency) for a in amounts)),
                tuple(rows),
                numeric_from=2,
            ),
        ),
    )


def _what_ran(record: dict[str, Any]) -> Section:
    code = record["code"]
    commit = code["git_commit"] or "unknown"
    version = f"{code['tyche_version']}, commit {commit[:12]}"
    if code["git_dirty"]:
        version += ", with uncommitted changes"
    request = record["request"]
    rows = (
        ("Analysis", record["capital_id"]),
        ("Started", record["started_at"]),
        ("Code", f"Tyche {version}; Python {code['python']}"),
        ("Config hash", record["config_hash"]),
        ("Market profile", record["market_profile"]),
        ("Range", f"{record['range']['first']} to {record['range']['last']}"),
        ("Rule", record["rule"]),
        ("Tolerance", fmt_points(request["tolerance"]).lstrip("+") + " of CAGR a year"),
        ("Holdout", f"from {record['holdout_starts']}, never backtested"),
        ("Costs checked on", record["costs_checked_on"]),
    )
    plans = tuple(
        (PLAN_NAMES.get(name, name), _rates(rates)) for name, rates in record["plans"].items()
    )
    return Section(
        "What ran",
        (
            Paragraph(
                "Everything needed to run this again is in capital.json: the full "
                "configuration, the amounts and the rates of each plan. Every run is a "
                "backtest of one strategy alone, with a budget of the whole account, its "
                "configured parameters, and only the starting cash and the plan changed. "
                "No run's equity or fills are kept."
            ),
            Table(("", ""), rows),
            Table(("Plan", "Rates"), plans),
        ),
    )


def _limits(record: dict[str, Any]) -> Section:
    added = (
        "Each strategy runs alone with the whole account. Run beside others, it gets only "
        "its budget, so its own minimum viable capital is that amount divided by its "
        "budget.",
        "The reference account is large but not infinite: its own costs are small, not "
        "zero. Too large, and the cap on a bar's volume binds on its orders: each "
        "strategy's table counts the orders cut short, and the answer is withheld when "
        "the reference had any.",
        "Tiered's exchange fee is an assumption, stated in the plan's rates: the real fee "
        "depends on where each order executes. Only Tiered's first volume tier is used, "
        "and whether its 1% maximum also caps the third-party fees is not published; they "
        "are added on top.",
        "Past share prices were lower than today's for most of these ETFs, so the "
        "backtests understate how often whole shares bind now; see today's share prices.",
        "The amounts are in the profile's currency. Money that arrives in another currency "
        "pays for its conversion, which is not modelled.",
        "The tolerance is a choice: a looser one gives a smaller minimum.",
    )
    return Section(
        "Data and its limits",
        (
            Paragraph("Limits every result in this report shares:"),
            Bullets(data_limits(record["costs_checked_on"], record["currency"])),
            Paragraph("Limits this analysis adds:"),
            Bullets(added),
        ),
    )


def _amount(value: str, currency: str) -> str:
    number = Decimal(value)
    shown = f"{number:,.0f}" if number == number.to_integral_value() else f"{number:,.2f}"
    return f"{shown} {currency}"


def _parameters(values: dict[str, Any]) -> str:
    return "; ".join(f"{k} = {json.dumps(v)}" for k, v in values.items()) or "none"


def _rates(rates: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in rates.items())

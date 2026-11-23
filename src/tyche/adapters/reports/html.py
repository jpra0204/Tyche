"""A self-contained HTML document, with charts drawn by matplotlib as inline SVG (ADR-0028).

The renderer knows nothing about backtests. It takes a ``Document`` (sections of
paragraphs, lists, callouts, tables and line charts, all plain values) and returns
one HTML string with no external file, script, font or network request, so a report
opens offline in any browser and stays the same years later.

Text is escaped; nothing in a document is treated as HTML.

Output is deterministic: the same document gives the same bytes. matplotlib's SVG
ids are seeded with a fixed salt, the date it would stamp is left out, and figures are
built directly (``matplotlib.figure.Figure``), never through pyplot's global state.
"""

import html
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import matplotlib
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import (
    FixedLocator,
    FuncFormatter,
    LogLocator,
    MaxNLocator,
    NullLocator,
    PercentFormatter,
)

COLOURS = ("#1f5fa8", "#8c8c8c", "#c0392b", "#2e8b57")
"""Line colours, in order: the strategy, then the benchmark, then any others."""

MARK_COLOUR = "#b35900"
"""Colour of a marked moment and its label."""

RASTER_DPI = 150
"""Resolution of the lines and areas inside each chart: sharp on screen and in print."""


class Tone(StrEnum):
    """How strongly a callout should stand out."""

    NOTE = "note"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str


@dataclass(frozen=True, slots=True)
class Bullets:
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Callout:
    text: str
    tone: Tone = Tone.NOTE


@dataclass(frozen=True, slots=True)
class Table:
    """A table. Columns from ``numeric_from`` on are numbers, aligned right."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numeric_from: int = 1

    def __post_init__(self) -> None:
        for row in self.rows:
            if len(row) != len(self.headers):
                raise ValueError(f"a row has {len(row)} cells, the table {len(self.headers)}")


@dataclass(frozen=True, slots=True)
class Line:
    """One series on a chart: values at moments, oldest first."""

    label: str
    points: tuple[tuple[datetime, float], ...]


@dataclass(frozen=True, slots=True)
class Mark:
    """A moment marked on a chart with a dashed vertical line and a label."""

    at: datetime
    label: str


@dataclass(frozen=True, slots=True)
class Chart:
    """A line chart over time.

    Attributes:
        title: Shown above the chart.
        lines: The series, drawn in ``COLOURS`` order.
        y_label: What the vertical axis measures.
        log_scale: A logarithmic vertical axis, for growth over years.
        percent: Values are fractions, shown as percentages.
        shade: Fill between each line and zero, for drawdowns and exposure.
        marks: Moments to mark, such as the day trading halted.
    """

    title: str
    lines: tuple[Line, ...]
    y_label: str
    log_scale: bool = False
    percent: bool = False
    shade: bool = False
    marks: tuple[Mark, ...] = ()


type Block = Paragraph | Bullets | Callout | Table | Chart


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class Document:
    title: str
    subtitle: str
    sections: tuple[Section, ...]
    callouts: tuple[Callout, ...] = field(default=())


def render_html(document: Document) -> str:
    """The document as one self-contained HTML page."""
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(document.title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>{_e(document.title)}</h1>",
        f'<p class="subtitle">{_e(document.subtitle)}</p>',
        *(_callout(c) for c in document.callouts),
        "</header>",
        "<nav><ol>",
        *(
            f'<li><a href="#s{n}">{_e(s.title)}</a></li>'
            for n, s in enumerate(document.sections, 1)
        ),
        "</ol></nav>",
    ]
    for number, section in enumerate(document.sections, 1):
        parts.append(f'<section id="s{number}">')
        parts.append(f"<h2>{_e(section.title)}</h2>")
        parts.extend(_block(block) for block in section.blocks)
        parts.append("</section>")
    parts.extend(["</body>", "</html>", ""])
    return "\n".join(parts)


def render_chart_svg(chart: Chart) -> str:
    """One chart as an SVG element, without an XML prologue, ready to inline."""
    with matplotlib.rc_context(
        {
            "svg.hashsalt": "tyche-report",
            "svg.fonttype": "none",
            "font.family": "sans-serif",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#e3e3e3",
            "grid.linewidth": 0.6,
        }
    ):
        figure = Figure(figsize=(9.0, 3.2), layout="constrained")
        axes = figure.add_subplot()
        span = 0.0
        for colour, line in zip(_colours(len(chart.lines)), chart.lines, strict=True):
            moments = [_year(moment) for moment, _ in line.points]
            values = [value for _, value in line.points]
            if moments:
                span = max(span, moments[-1] - moments[0])
            # Lines and areas are drawn as an image inside the SVG; axes and text stay
            # vector. Thousands of points as SVG paths would make every report megabytes.
            axes.plot(
                moments, values, label=line.label, color=colour, linewidth=1.1, rasterized=True
            )
            if chart.shade:
                axes.fill_between(
                    moments, values, 0, color=colour, alpha=0.12, linewidth=0, rasterized=True
                )
        for mark in chart.marks:
            moment = _year(mark.at)
            axes.axvline(moment, color=MARK_COLOUR, linewidth=0.9, linestyle="--")
            axes.annotate(
                mark.label,
                (moment, 1.0),
                xycoords=("data", "axes fraction"),
                xytext=(3, -3),
                textcoords="offset points",
                ha="left",
                va="top",
                color=MARK_COLOUR,
                fontsize=8,
            )
        if chart.log_scale:
            axes.set_yscale("log")
            # Labels at 1, 2 and 5 of each power of ten: 10,000, 20,000, 50,000...
            axes.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
            axes.yaxis.set_minor_locator(NullLocator())
            axes.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        if chart.percent:
            axes.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        _time_axis(axes, chart.lines, span)
        axes.set_ylabel(chart.y_label)
        axes.set_title(chart.title, loc="left", fontsize=10)
        if len(chart.lines) > 1:
            axes.legend(frameon=False, loc="best")
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg", dpi=RASTER_DPI, metadata={"Date": None})
    svg = buffer.getvalue()
    return svg[svg.index("<svg") :]


def _time_axis(axes: Axes, lines: Sequence[Line], span: float) -> None:
    """Ticks on whole years for three years or more, on month starts below that."""
    if span >= 3:
        axes.xaxis.set_major_locator(MaxNLocator(nbins=10, integer=True, steps=[1, 2, 5, 10]))
        axes.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{round(v)}"))
        return
    moments = [moment for line in lines for moment, _ in line.points]
    if not moments:
        return
    first, last = min(moments), max(moments)
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    step = next(s for s in (1, 2, 3, 6, 12) if months / s <= 12)
    starts: list[float] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        if (month - 1) % step == 0:
            starts.append(_year(datetime(year, month, 1, tzinfo=UTC)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    axes.xaxis.set_major_locator(FixedLocator(starts))
    axes.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _moment(v).strftime("%Y-%m")))


def _year(moment: datetime) -> float:
    """A moment as a year with a fraction: 2005.5 is about the start of July 2005.

    Charts plot time this way, with their own tick labels, rather than through
    matplotlib's date helpers, which carry no type information.
    """
    start = datetime(moment.year, 1, 1, tzinfo=UTC)
    length = datetime(moment.year + 1, 1, 1, tzinfo=UTC) - start
    return moment.year + (moment.astimezone(UTC) - start) / length


def _moment(year: float) -> datetime:
    """The inverse of ``_year``, for tick labels."""
    whole = int(year // 1)
    start = datetime(whole, 1, 1, tzinfo=UTC)
    length = datetime(whole + 1, 1, 1, tzinfo=UTC) - start
    return start + timedelta(seconds=(year - whole) * length.total_seconds())


def _colours(count: int) -> Sequence[str]:
    return [COLOURS[n % len(COLOURS)] for n in range(count)]


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _callout(callout: Callout) -> str:
    return f'<p class="callout {callout.tone.value}">{_e(callout.text)}</p>'


def _block(block: Block) -> str:
    match block:
        case Paragraph(text):
            return f"<p>{_e(text)}</p>"
        case Bullets(items):
            return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"
        case Callout():
            return _callout(block)
        case Table():
            return _table(block)
        case Chart():
            return f'<figure class="chart">{render_chart_svg(block)}</figure>'


def _table(table: Table) -> str:
    def cell(tag: str, index: int, text: str) -> str:
        numeric = ' class="num"' if index >= table.numeric_from else ""
        return f"<{tag}{numeric}>{_e(text)}</{tag}>"

    body = "".join(
        "<tr>" + "".join(cell("td", n, c) for n, c in enumerate(row)) + "</tr>"
        for row in table.rows
    )
    if not any(table.headers):  # a list of labelled values: no header row
        return f"<table><tbody>{body}</tbody></table>"
    head = "".join(cell("th", n, h) for n, h in enumerate(table.headers))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_CSS = """
:root { color-scheme: light; }
body {
  margin: 0 auto; max-width: 980px; padding: 24px 16px 64px;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1d1d1f; background: #ffffff;
}
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 40px 0 12px; padding-top: 8px; border-top: 1px solid #e3e3e3; }
.subtitle { color: #5a5a5f; margin: 0 0 16px; }
nav ol { margin: 0; padding-left: 20px; columns: 2; color: #5a5a5f; }
nav a { color: inherit; }
.callout { padding: 10px 14px; border-radius: 6px; margin: 12px 0; }
.callout.note { background: #f1f5fb; border-left: 4px solid #1f5fa8; }
.callout.warning { background: #fdf3f2; border-left: 4px solid #c0392b; }
table { border-collapse: collapse; margin: 8px 0 16px; font-size: 14px; }
th, td { padding: 5px 12px; border-bottom: 1px solid #e3e3e3; text-align: left; }
th { font-weight: 600; background: #f7f7f8; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
figure.chart { margin: 8px 0 20px; }
figure.chart svg { width: 100%; height: auto; }
ul { padding-left: 22px; }
@media print { nav { display: none; } h2 { break-after: avoid; } figure { break-inside: avoid; } }
"""

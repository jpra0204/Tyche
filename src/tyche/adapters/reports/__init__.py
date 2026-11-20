"""Report rendering.

Available now: ``render_html``, which turns a ``Document`` (sections of paragraphs,
lists, callouts, tables and line charts) into one self-contained HTML page, with
charts drawn by matplotlib as inline SVG (ADR-0028). The backtest report is assembled
from a run's record in ``tyche.runtime.report``.
"""

from tyche.adapters.reports.html import (
    COLOURS,
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
    render_chart_svg,
    render_html,
)

__all__ = [
    "COLOURS",
    "Block",
    "Bullets",
    "Callout",
    "Chart",
    "Document",
    "Line",
    "Paragraph",
    "Section",
    "Table",
    "Tone",
    "render_chart_svg",
    "render_html",
]

"""The HTML renderer: self-contained, escaped and deterministic."""

from datetime import UTC, datetime, timedelta

import pytest

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
    render_chart_svg,
    render_html,
)

START = datetime(2020, 1, 2, 21, tzinfo=UTC)


def daily(
    days: int, start: float = 10_000.0, step: float = 10.0
) -> tuple[tuple[datetime, float], ...]:
    return tuple((START + timedelta(days=n), start + step * n) for n in range(days))


def document(*blocks: Block) -> Document:
    return Document(
        title="Backtest <run>",
        subtitle="a & b",
        callouts=(Callout("Not a verdict."), Callout("Dirty code.", Tone.WARNING)),
        sections=(Section("Summary", blocks),),
    )


def test_text_is_escaped_never_treated_as_html() -> None:
    page = render_html(document(Paragraph("<script>alert(1)</script>"), Bullets(("a < b",))))

    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<title>Backtest &lt;run&gt;</title>" in page
    assert "a &amp; b" in page
    assert "<li>a &lt; b</li>" in page


def test_callouts_and_a_contents_list() -> None:
    page = render_html(document(Paragraph("x")))

    assert '<p class="callout note">Not a verdict.</p>' in page
    assert '<p class="callout warning">Dirty code.</p>' in page
    assert '<li><a href="#s1">Summary</a></li>' in page
    assert '<section id="s1">' in page


def test_tables_align_numbers_and_drop_an_empty_header() -> None:
    page = render_html(
        document(
            Table(("Year", "Return"), (("2023", "9.30%"),)),
            Table(("", ""), (("Fills", "656"),)),
        )
    )

    assert '<th>Year</th><th class="num">Return</th>' in page
    assert '<td>2023</td><td class="num">9.30%</td>' in page
    assert '<table><tbody><tr><td>Fills</td><td class="num">656</td></tr></tbody></table>' in page


def test_a_row_must_fit_the_table() -> None:
    with pytest.raises(ValueError, match="a row has 1 cells, the table 2"):
        Table(("a", "b"), (("only one",),))


def test_charts_are_inline_svg_and_the_page_needs_nothing_else() -> None:
    chart = Chart(
        "Equity",
        (Line("Strategies", daily(800)), Line("Benchmark", daily(800, step=5))),
        "USD",
        log_scale=True,
    )

    page = render_html(document(chart))

    assert '<figure class="chart"><svg' in page
    assert "<?xml" not in page
    for outside in ("<script", "<link", 'src="http', "url(http", "@import"):
        assert outside not in page


def test_a_long_chart_is_labelled_by_whole_years_and_a_log_axis_by_round_amounts() -> None:
    svg = render_chart_svg(
        Chart("Equity", (Line("Strategies", daily(1500)),), "USD", log_scale=True)
    )

    assert ">2021<" in svg
    assert ">2022<" in svg
    assert ">2021-07<" not in svg
    assert ">20,000<" in svg


def test_a_short_chart_is_labelled_by_month() -> None:
    svg = render_chart_svg(
        Chart(
            "Drawdown",
            (Line("Strategies", daily(200, start=0.0, step=-0.001)),),
            "below peak",
            percent=True,
            shade=True,
        )
    )

    assert ">2020-01<" in svg
    assert ">2020-04<" in svg


def test_the_same_document_gives_the_same_bytes() -> None:
    page = document(Chart("Equity", (Line("Strategies", daily(300)),), "USD"))

    assert render_html(page) == render_html(page)

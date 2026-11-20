# ADR-0028: The backtest report is one HTML file with matplotlib charts, built from the record

- **Status:** Accepted (Pablo, 2026-11-20)
- **Date:** 2026-11-20

## Context

Phase 1, PR 19 adds the backtest report the brief asks for: "HTML or markdown plus charts, saved with its exact config and code version". Two earlier commitments go into it. The Phase 0 review promised a **cost-drag section** in every report, because costs weigh heavily on a small account. The system overview promised that **every report states the limits of the data**.

Two questions needed Pablo:

1. **How is it rendered?** Every run writes a record folder that is committed to the private workspace repository, so a report's size adds up over hundreds of runs. Checked 2026-11-19 on PyPI: matplotlib 3.11.2 (PSF-based licence, Python 3.14 wheels, about 11 packages including numpy) draws static charts. Plotly 7.1.0 (MIT, 3 packages) draws interactive ones, but a report must then embed plotly.js (4.8 MB each time) or load it from a CDN, which needs internet to open the file.
2. **How is the cost drag measured?** It can be built from the record by adding costs back, or by rerunning the backtest without costs.

## Decision

1. **One self-contained HTML file per run, `report.html`, with charts drawn by matplotlib** as inline SVG. It opens offline in any browser and loads nothing from outside.
2. **The cost drag adds every cost back onto the equity curve.** Commissions and regulatory fees as each fill recorded them, and slippage worked back from each fill's price at the run's configured rate. The cost total paid to date is added back at every close. That gives a run before costs, measured the same way as the real one. Costs are added back as paid, not compounded, so the drag shown is a floor. A second, cost-free simulation was rejected: it needs the cache, doubles the time, and trades different share counts, so the gap would mix costs with sizing.

## Implementation choices made in PR 19, for review there

- **Built from the record alone.** The report reads `run.json`, `metrics.json`, `equity.csv` and `fills.csv`, never the cache or a second run. So it can be written for any run ever recorded, rebuilt after the report changes (`tyche report <run id>`), and it can never show a number the record does not hold. The STATUS item "a command to measure an existing record, if the report needs it" is therefore not needed: the report reads `metrics.json`.
- **Three layers, each in its own place** (ADR-0004):
  - `tyche.core.backtest` computes, with no I/O: `cost_drag` and `yearly_returns`, in `Decimal`, tested on their own.
  - `tyche.adapters.reports` renders a generic `Document` (sections of paragraphs, lists, callouts, tables and line charts) as HTML. It knows nothing about backtests, so the walk-forward report (PR 20) can reuse it. Only this adapter imports matplotlib, and the core's import contract now forbids it.
  - `tyche.runtime.report` reads a record and assembles the backtest's document.
  - The CLI calls it after `tyche backtest`. The runtime backtest module does not, because the report reads the record format that module defines, and calling it from there would make an import cycle.
- **Sections:** summary against the benchmark (metrics table, when each worst fall happened, equity on a log scale, drawdown); year by year; trading, with the share of equity invested over time; cost drag; what ran; data and its limits.
- **The limits stated in every report:**
  - Yahoo data through the unofficial yfinance, for personal use only.
  - Split-adjusted prices, with dividends credited at the ex-date and no withholding tax.
  - Survivorship bias.
  - Fills at the official open with fixed slippage and a volume cap.
  - The pessimistic stop rule on daily bars.
  - No interest on cash, and a zero risk-free rate.
  - The date the commission rates were checked.
  - No currency conversion.
  - The results are in-sample. The report's first callout says that one backtest is not a verdict.
- **Deterministic output.** The same record gives the same bytes:
  - matplotlib's SVG ids are seeded with a fixed salt, and its date stamp is left out.
  - Figures are built directly, never through pyplot's global state.
  - Time is plotted as fractional years with Tyche's own tick labels, rather than through matplotlib's date helpers, which carry no type information. Ticks fall on whole years for runs of three years or more, on month starts below that.
- **Lines and shaded areas are drawn as a 150 dpi image inside each SVG**; axes and text stay vector. As plain SVG paths, about 4,800 points per line made a 19-year report 1.0 to 1.3 MB. Rasterized, it is 320 to 390 KB.
- **No template engine.** Pages are built with Python strings, and all text is escaped. jinja2 would be one more dependency for a page with no logic.
- **A report that cannot be written does not fail the backtest.** The record is the source of truth: `tyche backtest` prints `Report: not written: …` and still succeeds. A run that was not measured gets no report.

## Checked on real data

Records from PR 18's runs, 2005 to 2023, USD 10,000, rebuilt with `tyche report`:

| | Trend rotation | Mean reversion |
|---|---|---|
| Commission and fees | 544.07 USD | 698.41 USD |
| Slippage (5 bps a fill) | 1,138.37 USD | 1,819.12 USD |
| Total costs | 1,682.44 USD | 2,517.53 USD |
| Share of the profit before costs | 7.74% | 47.93% |
| CAGR after costs | 5.97% | 1.28% |
| Report size | 386 KB | 324 KB |

Slippage cost both strategies more than twice their commissions. The terminal summary's "costs" counts commissions and fees only, so the report is the first place the full figure appears. The trading chart shows the rotation's trend filter at work: the stretches below 100% invested are months when some of its top ETFs were below their average and their share stayed in cash.

## Alternatives considered

- **Plotly**: interactive, but 4.8 MB per report, or a network request to open one.
- **Markdown with PNG files**: renders in GitHub and editor previews, but makes several files per run and is harder to keep self-contained.
- **Hand-drawn SVG**: no dependency, but axes, ticks and dates become Tyche's code to maintain.
- **A second simulation without costs**: exact and compounded, but slower, it needs the cache, and the comparison mixes in sizing differences.

## Consequences

- Tyche gains its first plotting dependency, matplotlib (and numpy with it), fenced into one adapter.
- Every measured run's folder gets `report.html`, about 300 to 400 KB. A workspace with a thousand runs carries roughly 350 MB of reports in its history; the files can be rebuilt, so they could be left uncommitted later if that becomes a problem.
- A change to the report never changes a result. Any old run can be re-rendered, and its numbers come from the same record files.

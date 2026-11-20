# Reports built from the record

## What problem does this solve

A report is the part of a backtest a person actually reads, so it is where a wrong number does the most harm. Two things commonly go wrong. The report is computed separately from what was saved, so the chart and the saved figures quietly disagree. Or the report can only be produced at the moment of the run, so an old run cannot be shown with a newer, better report, and a fix to the report means rerunning everything.

## The idea

Treat the **record as the single source of truth**, and the report as a **view** of it: a pure function from the record's files to a page.

- **Record first, report second.** The run writes its record (what ran, equity at every close, every fill, the metrics). The report reads only those files. It never reads the market data cache or reruns anything.
- **Rebuildable.** Because the report needs nothing but the record, it can be regenerated for any run ever made, after the report itself improves.
- **Deterministic.** The same record gives byte-for-byte the same report, so a regenerated report that changed means the report code changed, never the result.
- **Computation apart from presentation.** The numbers (cost drag, yearly returns) are computed by pure functions in the core and tested on their own. The renderer only lays out values it is given; it computes nothing.

It is the same separation as a database and a view, or a ledger and a statement: the ledger is kept with care, and statements can be printed from it in any format, any number of times.

## Where is it in Tyche

- `src/tyche/runtime/report.py`: `read_record` reads a run's folder, and `backtest_report` assembles the document. `write_report` writes `report.html` next to the record.
- `src/tyche/core/backtest/cost_drag.py` and `years.py`: the computations, in `Decimal`, with no I/O.
- `src/tyche/adapters/reports/html.py`: the renderer. It takes a generic `Document` and returns HTML with charts as inline SVG, deterministic by construction (a fixed SVG salt, no date stamp, no global plotting state).
- `tyche report <run id>` rebuilds a report; `tyche backtest` writes one after recording the run.
- [ADR-0028](../adr/0028-backtest-report-html-and-cost-drag.md) records the choices.

## What does it cost

- **The record must hold everything the report needs.** A new section that needs a fact the record lacks means changing the record format first, and old records cannot show it.
- **Some measures are approximations from the record.** The cost drag adds costs back rather than rerunning without them, so it is a floor, and the report says so.
- **Two formats to keep stable.** The record's layout is versioned (`record_format`, `metrics_format`), and the report refuses a record of a format it does not know rather than guessing.

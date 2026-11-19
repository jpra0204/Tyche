"""Config fragments and helpers for tests that write a workspace's files by hand."""

from pathlib import Path

BACKTEST = 'backtest = { holdout_starts = 2024-01-01, starting_cash = "10000" }\n'
"""The ``[backtest]`` table as an inline table: a top-level key, so it can go anywhere
before the first ``[table]`` header of ``tyche.toml``."""


def keep_candidates(root: Path, *symbols: str) -> None:
    """Trim a new workspace's ``US`` candidates to ``symbols``.

    The packaged template lists nine ETFs; a test that fetches made-up history for two
    of them keeps only those, so the backtest does not ask for the other seven.
    """
    path = root / "config" / "markets" / "US.toml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [
        line
        for line in lines
        if not line.lstrip().startswith("{ symbol = ")
        or any(line.lstrip().startswith(f'{{ symbol = "{symbol}"') for symbol in symbols)
    ]
    path.write_text("".join(kept), encoding="utf-8")

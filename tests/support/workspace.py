"""Config fragments for tests that write a workspace's files by hand."""

BACKTEST = 'backtest = { holdout_starts = 2024-01-01, starting_cash = "10000" }\n'
"""The ``[backtest]`` table as an inline table: a top-level key, so it can go anywhere
before the first ``[table]`` header of ``tyche.toml``."""

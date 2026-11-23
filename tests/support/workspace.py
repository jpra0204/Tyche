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


UNBOUND_PROFILE = "unbound"
"""A risk profile whose limits never bind for the example strategies (ADR-0033)."""


def add_unbound_profile(root: Path) -> str:
    """Give a new workspace guardrails wide enough for ``unbound``, and the profile itself.

    Tests of mechanics other than risk (sleeves, stops, costs, sweeps) load the
    workspace with this profile, so the risk gate approves their trades unchanged.
    Returns the profile's name, for ``load_config``.
    """
    (root / "config" / "guardrails.toml").write_text(
        "long_only = true\n"
        "allow_leverage = false\n"
        'max_risk_per_trade = "1"\n'
        "max_open_positions = 1000\n"
        'max_position_size = "1"\n'
        'max_daily_loss_limit = "0.99"\n'
        'max_drawdown_kill = "0.99"\n'
        'max_total_capital = [{ amount = "1000000000", currency = "USD" }]\n'
        'max_order_value = [{ amount = "1000000000", currency = "USD" }]\n',
        encoding="utf-8",
    )
    (root / "config" / "risk" / f"{UNBOUND_PROFILE}.toml").write_text(
        'risk_per_trade = "1"\n'
        "max_open_positions = 1000\n"
        'max_position_size = "1"\n'
        'daily_loss_limit = "0.5"\n'
        'drawdown_kill = "0.5"\n',
        encoding="utf-8",
    )
    return UNBOUND_PROFILE

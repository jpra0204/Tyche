"""Feeds for paper and live: the engine's inputs from the present, not from history.

``DailyFeed`` publishes each session's bars after its close, re-using the historical
replay so that paper and live see exactly what a backtest sees, and skips and reports
any decision too stale to trade (ADR-0043).
"""

from tyche.core.feeds.daily import SOURCE, DailyFeed

__all__ = ["SOURCE", "DailyFeed"]

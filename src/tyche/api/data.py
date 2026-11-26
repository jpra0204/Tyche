"""The Data page's data: what ``tyche data fetch`` can fetch, read-only (ADR-0046)."""

from tyche.api.models import DataView, ExchangeView
from tyche.config import KNOWN_EXCHANGES, ConfigError, Workspace, load_config
from tyche.runtime.data import DEFAULT_FIRST, followed_instruments


def read_data(workspace: Workspace) -> DataView:
    """The exchanges a symbol can be fetched from, and what ``--all`` fetches."""
    exchanges = [ExchangeView(mic=e.mic, name=e.name) for e in KNOWN_EXCHANGES.values()]
    try:
        config = load_config(workspace)
    except ConfigError as error:
        return DataView(
            exchanges=exchanges, default_first=DEFAULT_FIRST, followed=[], error=str(error)
        )
    return DataView(
        exchanges=exchanges,
        default_first=DEFAULT_FIRST,
        followed=[str(i) for i in followed_instruments(config.market_profile)],
    )

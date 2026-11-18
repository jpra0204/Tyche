"""The workspace and its configuration.

Available now:

* ``Workspace``, ``resolve_home``, ``check_location`` and ``init_workspace``: where
  the private workspace is and how to create one (ADR-0008).
* ``load_config``: reads the workspace's TOML files, validates them with pydantic,
  converts them to domain objects and fingerprints them. Invalid config raises
  ``ConfigError`` and Tyche refuses to start (ADR-0010). The active market profile
  comes with its trading costs (``config/costs/<PROFILE>.toml``, ADR-0020).

The file schemas live here; the core only receives domain objects (ADR-0017).
"""

from tyche.config.exchanges import KNOWN_EXCHANGES, ExchangeInfo
from tyche.config.loader import (
    SCHEMA_VERSION,
    ConfigError,
    CostsFile,
    MarketProfileFile,
    TycheConfig,
    TycheFile,
    config_hash,
    load_config,
)
from tyche.config.workspace import (
    DEFAULT_HOME,
    HOME_ENV_VAR,
    Workspace,
    WorkspaceError,
    check_location,
    init_workspace,
    resolve_home,
)

__all__ = [
    "DEFAULT_HOME",
    "HOME_ENV_VAR",
    "KNOWN_EXCHANGES",
    "SCHEMA_VERSION",
    "ConfigError",
    "CostsFile",
    "ExchangeInfo",
    "MarketProfileFile",
    "TycheConfig",
    "TycheFile",
    "Workspace",
    "WorkspaceError",
    "check_location",
    "config_hash",
    "init_workspace",
    "load_config",
    "resolve_home",
]

"""The workspace and its configuration.

Available now:

* ``Workspace``, ``resolve_home``, ``check_location`` and ``init_workspace``: where
  the private workspace is and how to create one (ADR-0008).
* ``load_config``: reads the workspace's TOML files, validates them with pydantic,
  converts them to domain objects and fingerprints them. Invalid config raises
  ``ConfigError`` and Tyche refuses to start (ADR-0010). The active market profile
  comes with its trading costs (``config/costs/<PROFILE>.toml``, ADR-0020), and the
  strategy instances with their budgets (``[strategies]`` in ``tyche.toml``) and
  plugin parameters (``config/strategies/<id>.toml``), as ``StrategySpec``s (ADR-0022);
  the backtest settings, with the reserved holdout, from ``[backtest]`` (ADR-0024).
* Risk limits in three layers (ADR-0032): ``config/guardrails.toml``, the named
  profiles in ``config/risk/`` (each checked against the guardrails; the active one,
  ``default`` unless chosen, is hashed), and an optional ``[risk]`` table per strategy,
  checked against the active profile.
* ``load_sweep``: reads a parameter sweep, ``config/sweeps/<name>.toml``, as a
  ``SweepSpec`` (ADR-0030). Sweep files are read on demand and are not part of the
  config hash.
* ``load_secrets``: reads the secrets in the workspace's ``.env`` with the standard
  library, the process environment winning, as a ``Secrets`` whose values never print
  (ADR-0040). Unknown keys and a malformed webhook URL raise ``EnvFileError``.

The file schemas live here; the core only receives domain objects (ADR-0017).
"""

from tyche.config.env import (
    DISCORD_WEBHOOK_URL,
    KNOWN_KEYS,
    SECRET_KEYS,
    EnvFileError,
    Secrets,
    load_secrets,
    parse_env,
    readable_by_others,
)
from tyche.config.exchanges import KNOWN_EXCHANGES, ExchangeInfo
from tyche.config.loader import (
    SCHEMA_VERSION,
    BacktestFile,
    ConfigError,
    CostsFile,
    MarketProfileFile,
    StrategyFile,
    StrategySpec,
    SweepFile,
    SweepSpec,
    TycheConfig,
    TycheFile,
    config_hash,
    load_config,
    load_sweep,
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
    "DISCORD_WEBHOOK_URL",
    "HOME_ENV_VAR",
    "KNOWN_EXCHANGES",
    "KNOWN_KEYS",
    "SCHEMA_VERSION",
    "SECRET_KEYS",
    "BacktestFile",
    "ConfigError",
    "CostsFile",
    "EnvFileError",
    "ExchangeInfo",
    "MarketProfileFile",
    "Secrets",
    "StrategyFile",
    "StrategySpec",
    "SweepFile",
    "SweepSpec",
    "TycheConfig",
    "TycheFile",
    "Workspace",
    "WorkspaceError",
    "check_location",
    "config_hash",
    "init_workspace",
    "load_config",
    "load_secrets",
    "load_sweep",
    "parse_env",
    "readable_by_others",
    "resolve_home",
]

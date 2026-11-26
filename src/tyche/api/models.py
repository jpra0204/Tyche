"""What the API answers, as pydantic models: the contract with the React app (ADR-0046).

The app's TypeScript types are generated from these, through the OpenAPI schema
(``ui/src/api/schema.d.ts``), so a change here fails the app's type check until the
types are generated again. Money and fractions are strings, so they stay exact.
Secrets never appear: only whether each one is set.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class StrategyView(_Model):
    """One configured strategy and its share of equity."""

    strategy_id: str
    plugin: str
    budget: str


class MoneyCapView(_Model):
    """The guardrails' money caps in one currency (ADR-0034)."""

    currency: str
    capital: str
    order: str | None


class RiskProfileView(_Model):
    """The active risk profile's limits (ADR-0032)."""

    name: str
    risk_per_trade: str
    max_open_positions: int
    max_position_size: str
    daily_loss_limit: str
    drawdown_kill: str


class ConfigView(_Model):
    """The workspace's configuration, as ``tyche config check`` reads it.

    When it cannot be read, ``valid`` is false, ``error`` says why, and the rest is empty.
    """

    valid: bool
    error: str | None = None
    market_profile: str | None = None
    config_hash: str | None = None
    risk_profile: RiskProfileView | None = None
    risk_profiles: list[str] = []
    strategies: list[StrategyView] = []
    cash_budget: str | None = None
    money_caps: list[MoneyCapView] = []


class SecretsView(_Model):
    """Which secrets ``.env`` sets. Never their values."""

    discord_webhook: bool
    ib_gateway: bool
    error: str | None = None


class KillView(_Model):
    """The kill switch, while it is engaged (ADR-0039)."""

    reason: str
    flatten: bool
    engaged_at: datetime | None


class HaltView(_Model):
    """A halt stored in the latest checkpoint: the drawdown kill or reconciliation."""

    since: datetime
    reasons: list[str]


class TradingView(_Model):
    """What stops trading now."""

    stopped: bool
    kill: KillView | None = None
    drawdown_halt: HaltView | None = None
    reconciliation_halt: HaltView | None = None
    state_unreadable: str | None = None


class CashView(_Model):
    """Cash in one currency: settled now, and still to settle."""

    currency: str
    settled: str
    pending: str


class PositionView(_Model):
    """One holding, at what it cost."""

    instrument: str
    quantity: str
    cost: str


class OrderView(_Model):
    """One order the last run left working at the broker."""

    client_order_id: str
    instrument: str
    side: str
    order_type: str
    remaining: str
    stop_price: str | None


class AccountView(_Model):
    """Tyche's account as the latest checkpoint saved it."""

    run_id: str
    saved_at: datetime
    cash: list[CashView]
    positions: list[PositionView]
    working_orders: list[OrderView]


class StatusView(_Model):
    """Everything the Status page shows."""

    workspace: str
    config: ConfigView
    secrets: SecretsView
    trading: TradingView
    account: AccountView | None

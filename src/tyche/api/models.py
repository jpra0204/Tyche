"""What the API answers, as pydantic models: the contract with the React app (ADR-0046).

The app's TypeScript types are generated from these, through the OpenAPI schema
(``ui/src/api/schema.d.ts``), so a change here fails the app's type check until the
types are generated again. Money and fractions are strings, so they stay exact.
Secrets never appear: only whether each one is set.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


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


# --- Runs (U2): a `tyche` command started from the page --------------------------------

SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9.\-]{0,11}$"
"""A symbol as the exchange lists it: ``SPY``, ``BRK.B``. Never starts with ``-``, so it
can never be read as an option."""

EXCHANGE_PATTERN = r"^[A-Z]{4}$"
"""A market identifier code; ``tyche data fetch`` says if it is not one it knows."""

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$"
"""A risk profile's name: a file in ``config/risk/``."""

RUN_ID_PATTERN = r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}(-[0-9]+)?$"
"""A backtest's run id, as ``new_run_id`` makes it."""


class _Request(_Model):
    """A request from the page: a field the command does not have is refused, not ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


Symbol = Annotated[str, StringConstraints(pattern=SYMBOL_PATTERN)]
Exchange = Annotated[str, StringConstraints(pattern=EXCHANGE_PATTERN)]
ProfileName = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]


class FetchRequest(_Request):
    """``tyche data fetch``: the profile's whole list, or symbols on one exchange."""

    command: Literal["data_fetch"]
    every_candidate: bool = False
    symbols: list[Symbol] = []
    exchange: Exchange | None = None
    asset_class: Literal["etf", "stock"] | None = None
    first: date | None = None
    last: date | None = None


class BacktestRequest(_Request):
    """``tyche backtest``: the configured strategies on cached history."""

    command: Literal["backtest"]
    first: date
    last: date | None = None
    risk_profile: ProfileName = "default"


class ReportRequest(_Request):
    """``tyche report``: write a backtest's report again, from its record."""

    command: Literal["report"]
    run_id: RunId


RunRequest = Annotated[
    FetchRequest | BacktestRequest | ReportRequest, Field(discriminator="command")
]
"""Every command the page can run. Anything else is refused before a process starts."""


class RunLine(_Model):
    """One line the command printed, on its output or its error stream."""

    stream: Literal["out", "err"]
    text: str


class RunView(_Model):
    """A command started from the page, running or finished, with all it printed."""

    number: int
    command: Literal["data_fetch", "backtest", "report"]
    argv: list[str]
    started_at: datetime
    finished_at: datetime | None
    exit_code: int | None
    state: Literal["running", "succeeded", "failed"]
    lines: list[RunLine]


# --- Data (U2) --------------------------------------------------------------------------


class ExchangeView(_Model):
    """An exchange ``tyche data fetch`` knows."""

    mic: str
    name: str


class DataView(_Model):
    """What the Data page offers: the exchanges, and what ``--all`` fetches."""

    exchanges: list[ExchangeView]
    default_first: date
    followed: list[str]
    error: str | None = None


# --- Backtests (U2) ---------------------------------------------------------------------


class BacktestSummary(_Model):
    """One recorded backtest, from its ``run.json`` and ``metrics.json``.

    Fractions are strings as ``metrics.json`` writes them (``"0.081234"`` is 8.12%).
    When the record cannot be read, ``error`` says why and the rest may be empty.
    """

    run_id: str
    started_at: datetime | None = None
    first: date | None = None
    last: date | None = None
    risk_profile: str | None = None
    currency: str | None = None
    starting_cash: str | None = None
    final_equity: str | None = None
    completed: bool | None = None
    failure: str | None = None
    halted: bool = False
    total_return: str | None = None
    benchmark: str | None = None
    benchmark_total_return: str | None = None
    max_drawdown: str | None = None
    has_report: bool = False
    error: str | None = None

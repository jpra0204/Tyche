"""What the API answers, as pydantic models: the contract with the React app (ADR-0046).

The app's TypeScript types are generated from these, through the OpenAPI schema
(``ui/src/api/schema.d.ts``), so a change here fails the app's type check until the
types are generated again. Money and fractions are strings, so they stay exact.
Secrets never appear: only whether each one is set.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

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
    """``tyche report``: write a record's report again: a backtest's, a walk-forward's, a
    sweep's, a capital analysis's or a profile comparison's."""

    command: Literal["report"]
    run_id: RunId


Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
"""Why, for the journal and the alert: one line of text."""


class PaperRunRequest(_Request):
    """``tyche paper run``: one decision cycle on the IBKR paper account (ADR-0045).

    ``confirmed`` must be true: the page asks first, and the contract says so.
    """

    command: Literal["paper_run"]
    risk_profile: ProfileName = "default"
    confirmed: Literal[True]


class KillRequest(_Request):
    """``tyche kill``: no new orders from the next decision on; with ``flatten``, sell
    every holding there. Run with ``--yes``: the page asked first."""

    command: Literal["kill"]
    reason: Reason
    flatten: bool = False
    confirmed: Literal[True]


class ResumeRequest(_Request):
    """``tyche resume``: lift the kill switch and the halts. Run with ``--yes``: the page
    showed what it lifts and asked first."""

    command: Literal["resume"]
    reason: Reason
    confirmed: Literal[True]


Amount = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,9}(\.[0-9]{1,2})?$")]
"""An amount of money, as typed: digits, and cents if any."""

Points = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,3}(\.[0-9]{1,4})?$")]
"""Percentage points, as typed: ``0.5`` is half a point."""


class WalkForwardRequest(_Request):
    """``tyche walk-forward``: folds of whole calendar years, each a backtest."""

    command: Literal["walk_forward"]
    first: date
    last: date | None = None
    train_years: Annotated[int, Field(ge=1, le=30)] = 5
    test_years: Annotated[int, Field(ge=1, le=10)] = 1
    rolling: bool = False
    sweep: ProfileName | None = None
    risk_profile: ProfileName = "default"


class SweepRequest(_Request):
    """``tyche sweep``: every combination of ``config/sweeps/<name>.toml``."""

    command: Literal["sweep"]
    name: ProfileName
    first: date
    last: date | None = None
    risk_profile: ProfileName = "default"


class CapitalRunRequest(_Request):
    """``tyche capital``: each strategy alone at several account sizes. An option left
    empty is left out, so the command's own default applies."""

    command: Literal["capital"]
    first: date
    last: date | None = None
    amounts: Annotated[list[Amount], Field(max_length=20)] = []
    reference: Amount | None = None
    tolerance: Points | None = None
    positions: Annotated[int, Field(ge=1, le=50)] | None = None
    risk_profile: ProfileName = "default"


class CompareProfilesRequest(_Request):
    """``tyche compare-profiles``: one backtest per risk profile; none named compares
    every profile in ``config/risk/``."""

    command: Literal["compare_profiles"]
    first: date
    last: date | None = None
    risk_profiles: Annotated[list[ProfileName], Field(max_length=20)] = []


AnyRunRequest = (
    FetchRequest
    | BacktestRequest
    | ReportRequest
    | PaperRunRequest
    | KillRequest
    | ResumeRequest
    | WalkForwardRequest
    | SweepRequest
    | CapitalRunRequest
    | CompareProfilesRequest
)

RunRequest = Annotated[AnyRunRequest, Field(discriminator="command")]
"""Every command the page can run. Anything else is refused before a process starts."""

CommandName = Literal[
    "data_fetch",
    "backtest",
    "report",
    "paper_run",
    "kill",
    "resume",
    "walk_forward",
    "sweep",
    "capital",
    "compare_profiles",
]


class RunLine(_Model):
    """One line the command printed, on its output or its error stream."""

    stream: Literal["out", "err"]
    text: str


class RunView(_Model):
    """A command started from the page, running or finished, with all it printed."""

    number: int
    command: CommandName
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


# --- Paper (U3) -------------------------------------------------------------------------


class DifferenceView(_Model):
    """One disagreement between Tyche's records and the broker's. Any one halts."""

    kind: str
    subject: str
    detail: str


class CashCheckView(_Model):
    """One currency's cash, Tyche's against the broker's (ADR-0044)."""

    currency: str
    tyche: str
    broker_settled: str
    broker_pending: str
    accrued: str
    allowed: str
    outcome: str


class ReconciliationView(_Model):
    """What one comparison with IBKR found: at the check, or after the decision."""

    run_id: str
    stage: Literal["check", "decision"]
    at: datetime
    status: Literal["match", "corrected", "mismatch"]
    differences: list[DifferenceView]
    inferred: list[str]
    ended: list[str]
    cash: list[CashCheckView]


class AlertView(_Model):
    """An alert as the log recorded it: what it said, and whether Discord got it."""

    at: datetime
    kind: str
    title: str
    lines: list[str]
    delivery: Literal["sent", "not_sent", "no_channel"]
    error: str | None = None


class PaperView(_Model):
    """What the Paper page shows beside the status: the last cycle's reconciliations,
    and the latest alerts, newest first."""

    last_cycle: str | None
    reconciliations: list[ReconciliationView]
    alerts: list[AlertView]
    state_unreadable: str | None = None


# --- Research (U4) ----------------------------------------------------------------------

StudyKind = Literal["walk_forward", "sweep", "capital", "profiles"]


class CapitalDefaults(_Model):
    """``tyche capital``'s defaults, for the form to show."""

    amounts: list[str]
    reference: str
    tolerance: str
    positions: int


class ResearchView(_Model):
    """What the Research page's forms offer."""

    sweeps: list[str]
    capital: CapitalDefaults


class StudySummary(_Model):
    """One recorded study, from its record file.

    ``headline`` is one line in words: the scheme and folds, the sweep and its trials,
    each strategy's minimum viable capital, or the profiles compared. When the record
    cannot be read, ``error`` says why.
    """

    kind: StudyKind
    study_id: str
    started_at: datetime | None = None
    first: date | None = None
    last: date | None = None
    completed: bool | None = None
    headline: str | None = None
    has_report: bool = False
    error: str | None = None


# --- Config, read-only (U5) -------------------------------------------------------------


class ProfileCheckView(_Model):
    """One risk profile in ``config/risk/``, checked as the active one, as
    ``tyche config check --risk-profile <name>`` does."""

    name: str
    valid: bool
    error: str | None = None
    profile: RiskProfileView | None = None


class GuardrailsView(_Model):
    """The absolute limits no profile may pass (ADR-0032), and the money caps (ADR-0034)."""

    max_risk_per_trade: str
    max_open_positions: int
    max_position_size: str
    max_daily_loss_limit: str
    max_drawdown_kill: str
    money_caps: list[MoneyCapView]


class StrategyDetailView(_Model):
    """One configured strategy: its file, budget, parameters and own risk limits."""

    strategy_id: str
    plugin: str
    budget: str
    source: str
    parameters: dict[str, Any]
    risk_per_trade: str | None = None
    max_open_positions: int | None = None
    max_position_size: str | None = None


class SweepView(_Model):
    """A sweep in ``config/sweeps/``: the strategy it varies and every value it tries."""

    name: str
    strategy_id: str | None = None
    grid: dict[str, list[Any]] = {}
    combinations: int | None = None
    error: str | None = None


class MarketView(_Model):
    """The active market profile, in short; the whole file is under ``files``."""

    name: str
    cash_currencies: list[str]
    calendars: list[str]
    candidates: list[str]
    benchmark: str
    rebalance_band: str
    price_buffer: str
    starting_cash: str
    holdout_starts: date
    costs_checked_on: date


class ConfigFileView(_Model):
    """One loaded file, as parsed and hashed: what a run record stores."""

    path: str
    settings: dict[str, Any]


class WorkspaceConfigView(_Model):
    """Everything the Config page shows, read-only.

    ``valid`` and ``error`` are ``tyche config check``'s verdict under the ``default``
    profile, strategies built; the rest is empty when it fails. ``profiles`` checks every
    file in ``config/risk/`` as the active one, as ``--risk-profile`` would: every profile
    must fit the guardrails whichever is active, and each strategy's own limits must fit
    the active one.
    """

    workspace: str
    valid: bool
    error: str | None = None
    config_hash: str | None = None
    env_readable_by_others: bool = False
    guardrails: GuardrailsView | None = None
    profiles: list[ProfileCheckView] = []
    strategies: list[StrategyDetailView] = []
    cash_budget: str | None = None
    sweeps: list[SweepView] = []
    market: MarketView | None = None
    files: list[ConfigFileView] = []

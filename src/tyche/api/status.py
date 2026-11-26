"""The Status page's data: the workspace as the CLI sees it, read-only (ADR-0046).

The same reads as ``tyche config check`` (the config and which secrets are set) and as
``tyche kill`` before it engages anything (the kill switch, the halts, and the latest
checkpoint). Nothing here writes, except that opening the state database brings its
schema up to date, as every command that opens it does.
"""

from collections.abc import Mapping
from decimal import Decimal

from tyche.api.models import (
    AccountView,
    CashView,
    ConfigView,
    HaltView,
    KillView,
    MoneyCapView,
    OrderView,
    PositionView,
    RiskProfileView,
    SecretsView,
    StatusView,
    StrategyView,
    TradingView,
)
from tyche.config import (
    ConfigError,
    EnvFileError,
    TycheConfig,
    Workspace,
    ibkr_connection,
    load_config,
    load_secrets,
)
from tyche.core.domain import Checkpoint, Money
from tyche.core.risk import Guardrails, RiskProfile
from tyche.runtime.kill_switch import TradingStatus, status


def read_status(workspace: Workspace, risk_profile: str, environ: Mapping[str, str]) -> StatusView:
    """Everything the Status page shows, for ``risk_profile``."""
    current = status(workspace)
    checkpoint = current.checkpoint
    return StatusView(
        workspace=str(workspace.root),
        config=_config(workspace, risk_profile),
        secrets=_secrets(workspace, environ),
        trading=_trading(current),
        account=_account_view(checkpoint) if checkpoint is not None else None,
    )


def _config(workspace: Workspace, risk_profile: str) -> ConfigView:
    try:
        config = load_config(workspace, risk_profile)
    except ConfigError as error:
        return ConfigView(valid=False, error=str(error))
    return _config_view(config)


def _config_view(config: TycheConfig) -> ConfigView:
    guardrails = config.guardrails
    budgets = [spec.budget for spec in config.strategies]
    cash = Decimal(1) - sum(budgets, start=Decimal(0))
    return ConfigView(
        valid=True,
        market_profile=str(config.market_profile),
        config_hash=config.config_hash,
        risk_profile=risk_profile_view(config.risk_profile),
        risk_profiles=list(config.risk_profiles),
        strategies=[
            StrategyView(strategy_id=s.strategy_id, plugin=s.plugin, budget=str(s.budget))
            for s in config.strategies
        ],
        cash_budget=str(cash) if cash else None,
        money_caps=money_caps_view(guardrails),
    )


def risk_profile_view(profile: RiskProfile) -> RiskProfileView:
    """A risk profile's limits, as the API gives them."""
    return RiskProfileView(
        name=profile.name,
        risk_per_trade=str(profile.risk_per_trade),
        max_open_positions=profile.max_open_positions,
        max_position_size=str(profile.max_position_size),
        daily_loss_limit=str(profile.daily_loss_limit),
        drawdown_kill=str(profile.drawdown_kill),
    )


def money_caps_view(guardrails: Guardrails) -> list[MoneyCapView]:
    """The guardrails' capital and order caps, one per currency."""
    return [
        MoneyCapView(
            currency=str(capital.currency),
            capital=str(capital.amount),
            order=_amount(guardrails.order_cap(capital.currency)),
        )
        for capital in guardrails.max_total_capital
    ]


def _secrets(workspace: Workspace, environ: Mapping[str, str]) -> SecretsView:
    try:
        secrets = load_secrets(workspace.env_file, environ)
    except EnvFileError as error:  # never contains a secret
        return SecretsView(discord_webhook=False, ib_gateway=False, error=str(error))
    try:
        ibkr_connection(secrets)
    except EnvFileError:
        gateway = False
    else:
        gateway = True
    return SecretsView(discord_webhook=secrets.discord_webhook_url is not None, ib_gateway=gateway)


def _trading(current: TradingStatus) -> TradingView:
    kill = current.kill
    halt = current.halt
    unreconciled = current.unreconciled
    return TradingView(
        stopped=current.stopped,
        kill=(
            KillView(reason=kill.reason, flatten=kill.flatten, engaged_at=kill.engaged_at)
            if kill is not None
            else None
        ),
        drawdown_halt=HaltView(since=halt.at, reasons=[halt.reason]) if halt is not None else None,
        reconciliation_halt=(
            HaltView(
                since=unreconciled.at,
                reasons=[str(d) for d in unreconciled.differences]
                + [str(f) for f in unreconciled.inferred],
            )
            if unreconciled is not None
            else None
        ),
        state_unreadable=current.unreadable,
    )


def _account_view(checkpoint: Checkpoint) -> AccountView:
    account = checkpoint.account
    cash = []
    for currency in account.currencies:
        balance = account.cash(currency)
        pending = sum((p.amount.amount for p in balance.pending), start=Decimal(0))
        cash.append(
            CashView(
                currency=str(currency),
                settled=str(balance.settled.amount),
                pending=str(pending),
            )
        )
    return AccountView(
        run_id=checkpoint.run_id,
        saved_at=checkpoint.saved_at,
        cash=cash,
        positions=[
            PositionView(
                instrument=str(p.instrument), quantity=str(p.quantity), cost=str(p.cost.amount)
            )
            for p in account.positions
        ],
        working_orders=[
            OrderView(
                client_order_id=o.state.order.client_order_id,
                instrument=str(o.state.order.instrument),
                side=str(o.state.order.side),
                order_type=str(o.state.order.order_type),
                remaining=str(o.state.remaining),
                stop_price=_amount(o.state.order.stop_price),
            )
            for o in checkpoint.execution.orders
        ],
    )


def _amount(money: Money | None) -> str | None:
    return str(money.amount) if money is not None else None

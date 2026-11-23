"""Wiring for ``tyche capital``: minimum viable capital, per strategy and plan (ADR-0031).

Composition-root code (ADR-0004). Each configured strategy runs **alone, with the
whole account**, as a backtest over the same days at every amount asked for and on a
large reference account, through the same path as ``tyche backtest``
(``run_and_measure``). Each amount runs under IBKR Pro Fixed (the costs file's
``[commission]``) and, when the costs file has a ``[tiered]`` table, under Tiered too.
Only the starting cash and the pricing plan change between runs; every strategy keeps
its configured parameters, so the analysis adds no trial beyond the configured one.

Two pieces of arithmetic sit beside the backtests:

* **What one round trip costs** per position, at each amount split over one to
  ``positions`` positions, for a share priced at USD 100.
* **Today's share prices**: each candidate's latest cached close, and how many whole
  shares one of ``positions`` equal positions buys at each amount. The backtests use
  past prices; most of these ETFs never split, so their shares cost more now. This is
  the one place Tyche reads a bar inside the holdout, and it reads only the last close,
  never a result (ADR-0031).

What a capital analysis keeps, in ``reports/capital/<id>/``: ``capital.json``, with
every run's figures, the verdicts, the arithmetic and the configuration; and
``report.html``. No run's equity or fills are kept: each can be run again from the
amount, the plan and the config hash.
"""

import json
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche.adapters.clocks import SystemClock
from tyche.adapters.data import ParquetBarCache
from tyche.adapters.data.yfinance_source import SOURCE_NAME
from tyche.config import TycheConfig
from tyche.core.backtest import (
    BacktestMetrics,
    BacktestResult,
    CapitalError,
    CostDrag,
    MetricsError,
    SizedResult,
    cost_drag,
    fill_cost,
    is_viable,
    minimum_viable,
    round_trip_cost,
    size_penalty,
    trial_key,
)
from tyche.core.backtest.metrics import equity_points
from tyche.core.domain import (
    CommissionSchedule,
    Instrument,
    Money,
    OrderStatus,
    PlanNote,
    Timeframe,
    TradingCosts,
    affordable_shares,
)
from tyche.core.events import Envelope, ExecutionPlanEvent, OrderEvent
from tyche.core.ports import Clock
from tyche.runtime.backtest import (
    BENCHMARK_METHOD,
    CachedMarket,
    CodeVersion,
    MeasuredRun,
    cached_market,
    cents,
    checked_range,
    current_code_version,
    new_run_id,
    run_and_measure,
)
from tyche.runtime.strategies import ConfiguredStrategies, build_strategies
from tyche.runtime.trials import CAPITAL_FILE

CAPITAL_FORMAT = 1
"""Version of ``capital.json``'s layout. Raised when a field changes meaning or goes away."""

FIXED = "fixed"
"""The plan in the costs file's ``[commission]`` table: the one backtests use."""

TIERED = "tiered"
"""The plan in the costs file's optional ``[tiered]`` table."""

DEFAULT_AMOUNTS = tuple(Decimal(a) for a in ("500", "1000", "2000", "5000", "10000", "25000"))
DEFAULT_REFERENCE = Decimal("100000")
DEFAULT_TOLERANCE = Decimal("0.005")
"""Half a point of CAGR a year."""

DEFAULT_POSITIONS = 5
"""The brief's default risk profile allows five open positions."""

ILLUSTRATIVE_PRICE = Decimal(100)
"""The share price the round-trip arithmetic assumes."""

_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class CapitalRequest:
    """What to test, checked before anything runs.

    Attributes:
        amounts: Starting cash to test, in the profile's cash currency, smallest first.
        reference: The large account every amount is compared with.
        tolerance: How far, either way, an amount's CAGR may be from the reference
            account's and the amount be viable, as a fraction of CAGR a year (0.005 is
            half a point).
        positions: The most positions the arithmetic splits an account into.
    """

    amounts: tuple[Decimal, ...] = DEFAULT_AMOUNTS
    reference: Decimal = DEFAULT_REFERENCE
    tolerance: Decimal = DEFAULT_TOLERANCE
    positions: int = DEFAULT_POSITIONS

    def __post_init__(self) -> None:
        if not self.amounts:
            raise CapitalError("give at least one amount to test")
        if any(not a.is_finite() or a <= 0 for a in (*self.amounts, self.reference)):
            raise CapitalError("every amount and the reference must be positive")
        if len(set(self.amounts)) != len(self.amounts):
            raise CapitalError("each amount may be given once")
        if list(self.amounts) != sorted(self.amounts):
            raise CapitalError("give the amounts smallest first")
        if self.amounts[-1] >= self.reference:
            raise CapitalError(
                f"the reference account ({self.reference}) must be larger than every "
                f"amount tested (the largest is {self.amounts[-1]})"
            )
        if not self.tolerance.is_finite() or not 0 <= self.tolerance < 1:
            raise CapitalError(
                f"the tolerance must be at least 0 and below 1, got {self.tolerance}"
            )
        if self.positions < 1:
            raise CapitalError(f"positions must be at least 1, got {self.positions}")


@dataclass(frozen=True, slots=True)
class SizedRun:
    """One strategy, alone, on one account size under one plan.

    Attributes:
        strategy_id: The strategy.
        plan: ``FIXED`` or ``TIERED``.
        amount: The starting cash.
        metrics: The run against the benchmark; ``None`` if it could not be measured.
        drag: The run before and after its costs; ``None`` if not measured.
        decisions: Decision cycles that reached execution.
        short_of_a_share: Of those, how many had a target worth less than one share,
            so the strategy held less than it decided.
        free_riding: Free-riding violations the broker recorded (ADR-0020).
        cut_short: Orders that expired with shares left unfilled: the simulator's cap on
            a bar's volume bound. On the reference account it means the account is too
            large for the strategy, and its result is not the strategy free of its size.
        failure: Why it was not measured, or ``None``.
        halted_at: The close at which the drawdown kill halted its trading, or ``None``
            (ADR-0035).
    """

    strategy_id: str
    plan: str
    amount: Decimal
    metrics: BacktestMetrics | None
    drag: CostDrag | None
    decisions: int
    short_of_a_share: int
    free_riding: int
    cut_short: int = 0
    failure: str | None = None
    halted_at: datetime | None = None

    @property
    def cagr(self) -> Decimal | None:
        return self.metrics.strategy.cagr if self.metrics is not None else None


@dataclass(frozen=True, slots=True)
class PlanVerdict:
    """One strategy under one plan: every amount, the reference, and the answer.

    Attributes:
        strategy_id: The strategy.
        plan: ``FIXED`` or ``TIERED``.
        runs: One per amount, smallest first.
        reference: The run on the reference account.
        minimum: The minimum viable capital; ``None`` if no tested amount is.
    """

    strategy_id: str
    plan: str
    runs: tuple[SizedRun, ...]
    reference: SizedRun
    minimum: Decimal | None

    def penalty(self, run: SizedRun) -> Decimal | None:
        return size_penalty(run.cagr, self.reference.cagr)

    def viable(self, run: SizedRun, tolerance: Decimal) -> bool:
        return is_viable(run.cagr, self.reference.cagr, tolerance)

    @property
    def reference_too_large(self) -> bool:
        """True if the volume cap cut some of the reference account's orders short."""
        return self.reference.cut_short > 0

    @property
    def at_minimum(self) -> SizedRun | None:
        """The run at the minimum viable capital, if there is one."""
        return next((r for r in self.runs if r.amount == self.minimum), None)


@dataclass(frozen=True, slots=True)
class StrategyStudy:
    """One strategy's capital analysis.

    Attributes:
        strategy_id: The strategy.
        plugin: Its plugin.
        version: The plugin's version.
        parameters: The parameters it ran with: its strategy file's.
        key: Its ``trial_key``: what the trial count counts (ADR-0030).
        verdicts: One per plan, Fixed first.
    """

    strategy_id: str
    plugin: str
    version: str
    parameters: Mapping[str, Any]
    key: str
    verdicts: tuple[PlanVerdict, ...]


@dataclass(frozen=True, slots=True)
class LatestClose:
    """A candidate's latest cached close, read for today's share prices only.

    Attributes:
        instrument: The candidate.
        day: The close's session day; ``None`` if nothing is cached.
        close: The close; ``None`` if nothing is cached.
    """

    instrument: Instrument
    day: date | None
    close: Decimal | None


@dataclass(frozen=True, slots=True)
class CapitalResult:
    """A finished capital analysis.

    Attributes:
        request: What was tested.
        first: The first day every run traded.
        last: The last day.
        plans: The costs each plan ran with, by name, Fixed first.
        studies: One per configured strategy, ordered by id.
        latest_closes: Each candidate's latest cached close.
    """

    request: CapitalRequest
    first: date
    last: date
    plans: Mapping[str, TradingCosts]
    studies: tuple[StrategyStudy, ...]
    latest_closes: tuple[LatestClose, ...]


RunProgress = Callable[[SizedRun, SizedRun | None], None]
"""Told about every run once measured, with its plan's reference run once that has run."""


def pricing_plans(config: TycheConfig) -> dict[str, TradingCosts]:
    """Fixed, from ``[commission]``, and Tiered when the costs file has ``[tiered]``."""
    plans = {FIXED: config.costs}
    if config.tiered_costs is not None:
        plans[TIERED] = config.tiered_costs
    return plans


def run_capital(
    config: TycheConfig,
    request: CapitalRequest,
    market: CachedMarket,
    *,
    run_id: str,
    first: date,
    last: date,
    clock: Clock,
    code: CodeVersion,
    progress: RunProgress | None = None,
) -> CapitalResult:
    """Run every configured strategy alone at every amount, under every plan.

    The reference account runs first for each strategy and plan, so that missing
    history stops the analysis before anything else has run, and so that each later
    run's size penalty can be told as it is measured.

    Raises:
        CapitalError: No strategy is configured.
        BacktestRequestError: History is missing from the cache.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
        ConfigError: A strategy cannot be built from its file.
    """
    built = build_strategies(config)
    if not built.strategies:
        raise CapitalError(
            "no strategy has a budget under [strategies] in tyche.toml, so there is "
            "nothing to analyse"
        )
    plans = pricing_plans(config)
    studies: list[StrategyStudy] = []
    for strategy in built.strategies:
        sid = strategy.strategy_id
        parameters = built.parameters[sid]
        alone = ConfiguredStrategies((strategy,), {sid: Decimal(1)}, {sid: parameters})
        setting = _Setting(config, market, alone, run_id, first, last, clock, code)
        verdicts: list[PlanVerdict] = []
        for plan, costs in plans.items():
            reference = setting.run(plan, costs, request.reference)
            if progress is not None:
                progress(reference, None)
            runs: list[SizedRun] = []
            for amount in request.amounts:
                run = setting.run(plan, costs, amount)
                runs.append(run)
                if progress is not None:
                    progress(run, reference)
            minimum = minimum_viable(
                [SizedResult(r.amount, r.cagr) for r in runs], reference.cagr, request.tolerance
            )
            verdicts.append(PlanVerdict(sid, plan, tuple(runs), reference, minimum))
        plugin = next(s.plugin for s in config.strategies if s.strategy_id == sid)
        studies.append(
            StrategyStudy(
                strategy_id=sid,
                plugin=plugin,
                version=strategy.version,
                parameters=dict(parameters),
                key=trial_key(plugin, strategy.version, parameters),
                verdicts=tuple(verdicts),
            )
        )
    return CapitalResult(request, first, last, plans, tuple(studies), latest_closes(config))


@dataclass(frozen=True, slots=True)
class _Setting:
    """What every run of one strategy shares; only the plan and the amount change."""

    config: TycheConfig
    market: CachedMarket
    strategies: ConfiguredStrategies
    run_id: str
    first: date
    last: date
    clock: Clock
    code: CodeVersion

    def run(self, plan: str, costs: TradingCosts, amount: Decimal) -> SizedRun:
        strategy_id = self.strategies.strategies[0].strategy_id
        run = run_and_measure(
            _at(self.config, amount, costs),
            self.market,
            self.strategies,
            run_id=f"{self.run_id}-{strategy_id}-{plan}-{amount}",
            first=self.first,
            last=self.last,
            clock=self.clock,
            code=self.code,
        )
        return _sized(run, strategy_id, plan, amount, costs)


def _at(config: TycheConfig, amount: Decimal, costs: TradingCosts) -> TycheConfig:
    """The configuration with ``amount`` as starting cash and ``costs`` as the plan.

    The config hash is left as it is: it names the workspace's files, and the record
    states the amount and the plan beside it.
    """
    cash = Money(amount, config.market_profile.cash_currencies[0])
    return replace(config, costs=costs, backtest=replace(config.backtest, starting_cash=cash))


def _sized(
    run: MeasuredRun, strategy_id: str, plan: str, amount: Decimal, costs: TradingCosts
) -> SizedRun:
    result = run.result
    lines_by_decision = [e.event.lines for e in result.journal.of_type(ExecutionPlanEvent)]
    short = sum(
        1
        for lines in lines_by_decision
        if any(line.note is PlanNote.BELOW_ONE_SHARE for line in lines)
    )
    last_states = {e.event.state.order.client_order_id: e.event.state for e in orders(result)}
    cut_short = sum(
        1
        for state in last_states.values()
        if state.status is OrderStatus.EXPIRED and state.remaining > 0
    )
    failure: str | None = None
    if not result.run.completed:
        failure = f"halted: {result.run.failure}"
    elif run.metrics is None:
        failure = f"not measured: {run.metrics_error}"
    drag: CostDrag | None = None
    if failure is None and run.metrics is not None:
        currency = run.metrics.currency
        fills = [
            fill_cost(
                f.filled_at,
                f.side,
                f.quantity,
                f.price.amount,
                f.commission.amount,
                costs.slippage_bps,
            )
            for f in result.fills
        ]
        try:
            drag = cost_drag(equity_points(result, currency), fills)
        except MetricsError as error:
            failure = f"cost drag not measured: {error}"
    return SizedRun(
        strategy_id=strategy_id,
        plan=plan,
        amount=amount,
        metrics=run.metrics if failure is None else None,
        drag=drag if failure is None else None,
        decisions=len(lines_by_decision),
        short_of_a_share=short,
        free_riding=len(result.free_riding),
        cut_short=cut_short,
        failure=failure,
        halted_at=result.halt.at if result.halt is not None else None,
    )


def orders(result: BacktestResult) -> list[Envelope[OrderEvent]]:
    """Every order status change of a run, in order."""
    return result.journal.of_type(OrderEvent)


def latest_closes(config: TycheConfig) -> tuple[LatestClose, ...]:
    """Each candidate's latest cached daily close, and the benchmark's.

    The one read of a bar that may lie inside the holdout (ADR-0031): only its close
    and date, to show what a share costs now. Nothing is run on it.
    """
    profile = config.market_profile
    instruments = list(profile.universe.instruments)
    if profile.benchmark not in instruments:
        instruments.append(profile.benchmark)
    cache = ParquetBarCache(config.workspace.data_dir / "bars", source=SOURCE_NAME)
    found: list[LatestClose] = []
    for instrument in instruments:
        rows = cache.load(instrument, Timeframe.D1).rows
        if not rows:
            found.append(LatestClose(instrument, None, None))
            continue
        bar = rows[-1].bar
        found.append(LatestClose(instrument, bar.timestamp.date(), Decimal(repr(bar.close))))
    return tuple(found)


# --- the arithmetic -------------------------------------------------------------------


def round_trips(
    costs: TradingCosts, amounts: Sequence[Decimal], positions: int
) -> list[dict[str, Any]]:
    """For each amount, one round trip's cost per position, split 1 to ``positions`` ways.

    At ``ILLUSTRATIVE_PRICE`` a share; ``None`` where a position cannot buy one share.
    """
    currency = costs.currency
    price = Money(ILLUSTRATIVE_PRICE, currency)
    return [
        {
            "amount": str(amount),
            "by_positions": {
                str(n): _fraction(round_trip_cost(costs, Money(amount / n, currency), price))
                for n in range(1, positions + 1)
            },
        }
        for amount in amounts
    ]


def whole_shares_today(
    closes: Sequence[LatestClose], costs: TradingCosts, amounts: Sequence[Decimal], positions: int
) -> list[dict[str, Any]]:
    """For each candidate, the whole shares one of ``positions`` positions buys today."""
    currency = costs.currency
    rows: list[dict[str, Any]] = []
    for latest in closes:
        row: dict[str, Any] = {
            "instrument": str(latest.instrument),
            "day": latest.day.isoformat() if latest.day is not None else None,
            "close": str(latest.close) if latest.close is not None else None,
        }
        if latest.close is not None:
            price = Money(latest.close, currency)
            row["shares"] = {
                str(amount): int(
                    affordable_shares(Money(amount / positions, currency), price, costs)
                )
                for amount in amounts
            }
        rows.append(row)
    return rows


# --- the standalone analysis ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapitalOutcome:
    """A finished capital analysis and where its record was written.

    Attributes:
        capital_id: Identifies it, and names its folder.
        record_dir: ``reports/capital/<id>/``.
        code: Which code ran.
        result: Every run and the verdicts.
    """

    capital_id: str
    record_dir: Path
    code: CodeVersion
    result: CapitalResult


def run_configured_capital(
    config: TycheConfig,
    request: CapitalRequest,
    first: date,
    last: date | None = None,
    *,
    clock: Clock | None = None,
    code: CodeVersion | None = None,
    progress: RunProgress | None = None,
) -> CapitalOutcome:
    """Analyse minimum viable capital from ``first`` to ``last``, and record it.

    ``last`` defaults to the day before the holdout.

    Raises:
        CapitalError: No strategy is configured.
        BacktestRequestError: The range cannot be run as asked, or history is missing.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
        ConfigError: A strategy cannot be built from its file.
    """
    clock = clock or SystemClock()
    code = code or current_code_version()
    last = checked_range(config, first, last)
    root = config.workspace.reports_dir / "capital"
    started = clock.now()
    capital_id = new_run_id(root, started, config.config_hash)
    result = run_capital(
        config,
        request,
        cached_market(config, last, clock),
        run_id=capital_id,
        first=first,
        last=last,
        clock=clock,
        code=code,
        progress=progress,
    )
    folder = root / capital_id
    folder.mkdir(parents=True)
    record = capital_record(capital_id, config, result, code, started=started, finished=clock.now())
    _write_json(folder / CAPITAL_FILE, record)
    return CapitalOutcome(capital_id, folder, code, result)


# --- the record -----------------------------------------------------------------------


def capital_record(
    capital_id: str,
    config: TycheConfig,
    result: CapitalResult,
    code: CodeVersion,
    *,
    started: datetime,
    finished: datetime,
) -> dict[str, Any]:
    """``capital.json``: what ran, every run, the verdicts and the arithmetic.

    Each strategy's ``key`` is what ``recorded_trial_keys`` counts. Figures follow
    ``metrics.json``'s conventions: fractions and ratios as strings to six places.
    """
    request = result.request
    currency = config.market_profile.cash_currencies[0]
    benchmark = next(
        (
            r.metrics
            for s in result.studies
            for v in s.verdicts
            for r in (v.reference, *v.runs)
            if r.metrics is not None
        ),
        None,
    )
    return {
        "capital_format": CAPITAL_FORMAT,
        "capital_id": capital_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "code": {
            "tyche_version": code.tyche,
            "git_commit": code.commit,
            "git_dirty": code.dirty,
            "python": platform.python_version(),
        },
        "config_hash": config.config_hash,
        "market_profile": config.market_profile.name,
        "currency": currency.value,
        "range": {"first": result.first.isoformat(), "last": result.last.isoformat()},
        "holdout_starts": config.backtest.holdout_starts.isoformat(),
        "request": {
            "amounts": [str(a) for a in request.amounts],
            "reference": str(request.reference),
            "tolerance": str(request.tolerance),
            "positions": request.positions,
        },
        "rule": (
            "the smallest amount from which every larger amount tested has a CAGR, after "
            "costs, within the tolerance of the reference account's, under the same plan"
        ),
        "costs_checked_on": config.costs.checked_on.isoformat(),
        "plans": {name: _plan_record(costs) for name, costs in result.plans.items()},
        "benchmark": (
            {
                "instrument": str(benchmark.benchmark_instrument),
                "method": BENCHMARK_METHOD,
                "cagr": _fraction(benchmark.benchmark.cagr),
                "sharpe": _fraction(benchmark.benchmark.sharpe),
            }
            if benchmark is not None
            else None
        ),
        "strategies": [_study_record(s, request.tolerance) for s in result.studies],
        "round_trips": {
            "price": str(ILLUSTRATIVE_PRICE),
            "plans": {
                name: round_trips(costs, request.amounts, request.positions)
                for name, costs in result.plans.items()
            },
        },
        "today": {
            "note": (
                "each candidate's latest cached close, which may lie inside the holdout; "
                "read for its price only (ADR-0031)"
            ),
            "positions": request.positions,
            "candidates": whole_shares_today(
                result.latest_closes, config.costs, request.amounts, request.positions
            ),
        },
        "config": config.snapshot,
    }


def _plan_record(costs: TradingCosts) -> dict[str, Any]:
    commission = costs.commission
    rates: dict[str, Any]
    if isinstance(commission, CommissionSchedule):
        rates = {
            "kind": "per share, with a minimum and a maximum per order",
            "per_share": str(commission.per_share.amount),
            "minimum": str(commission.minimum.amount),
            "maximum_rate": str(commission.maximum_rate),
        }
    else:
        rates = {
            "kind": "per share, with a minimum and a maximum, plus third-party fees",
            "per_share": str(commission.per_share.amount),
            "minimum": str(commission.minimum.amount),
            "maximum_rate": str(commission.maximum_rate),
            "clearing_per_share": str(commission.clearing_per_share.amount),
            "clearing_maximum_rate": str(commission.clearing_maximum_rate),
            "nyse_pass_through_rate": str(commission.nyse_pass_through_rate),
            "finra_pass_through_rate": str(commission.finra_pass_through_rate),
            "exchange_fee_per_share": str(commission.exchange_fee_per_share.amount),
        }
    return {**rates, "slippage_bps": str(costs.slippage_bps)}


def _study_record(study: StrategyStudy, tolerance: Decimal) -> dict[str, Any]:
    return {
        "id": study.strategy_id,
        "plugin": study.plugin,
        "version": study.version,
        "parameters": dict(study.parameters),
        "key": study.key,
        "plans": [
            {
                "plan": verdict.plan,
                "minimum_viable": str(verdict.minimum) if verdict.minimum is not None else None,
                "reference_too_large": verdict.reference_too_large,
                "reference": _run_record(verdict, verdict.reference, tolerance, reference=True),
                "runs": [_run_record(verdict, r, tolerance) for r in verdict.runs],
            }
            for verdict in study.verdicts
        ],
    }


def _run_record(
    verdict: PlanVerdict, run: SizedRun, tolerance: Decimal, *, reference: bool = False
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "amount": str(run.amount),
        "measured": run.metrics is not None,
        "failure": run.failure,
        "decisions": run.decisions,
        "short_of_a_share": run.short_of_a_share,
        "free_riding": run.free_riding,
        "cut_short": run.cut_short,
        "halted_at": run.halted_at.isoformat() if run.halted_at is not None else None,
    }
    metrics, drag = run.metrics, run.drag
    if metrics is None or drag is None:
        return record
    strategy = metrics.strategy
    drawdown = strategy.max_drawdown
    record.update(
        {
            "final_equity": cents(strategy.end_equity),
            "cagr": _fraction(strategy.cagr),
            "sharpe": _fraction(strategy.sharpe),
            "max_drawdown": _fraction(drawdown.depth if drawdown is not None else Decimal(0)),
            "exposure": _fraction(strategy.exposure),
            "turnover": _fraction(metrics.turnover),
            "commission_and_fees": cents(drag.commission),
            "slippage": cents(drag.slippage),
            "costs_per_year": _fraction(drag.per_year),
            "cagr_before_costs": _fraction(drag.before_costs.cagr),
            "cagr_drag": _fraction(drag.cagr_drag),
            "closed_trades": len(metrics.trades.closed),
            "versus_benchmark": {
                "cagr": _fraction(metrics.versus_benchmark.cagr),
                "sharpe": _fraction(metrics.versus_benchmark.sharpe),
            },
        }
    )
    if not reference:
        record["size_penalty"] = _fraction(verdict.penalty(run))
        record["viable"] = verdict.viable(run, tolerance)
    return record


def _fraction(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_PLACES))


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

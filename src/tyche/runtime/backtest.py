"""Wiring for ``tyche backtest``: the workspace in, a run record out (ADR-0024).

Composition-root code (ADR-0004). It picks the concrete parts the core runner needs
(the New York calendar, the Parquet cache read through a source that never fetches,
the system clock), builds the configured strategies, runs ``run_backtest``, and
writes what happened to ``reports/backtests/<run id>/`` in the workspace:

* ``run.json``: the run record. The code version, the config hash and every setting
  behind it, the range, the warm-up, the holdout, the data used and the outcome.
* ``equity.csv``: Tyche's account at every session close, and the benchmark's equity
  at the same close.
* ``fills.csv``: every fill, with its costs.
* ``metrics.json``: the run measured against the benchmark (ADR-0025).

A run that halts is recorded too: every run is a trial, and Phase 1 PR 21 and the
Phase 3 gate count trials.
"""

import csv
import json
import platform
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche import __version__
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.clocks import SystemClock
from tyche.adapters.data import (
    CachedDataProvider,
    CacheOnlySource,
    NotCachedError,
    ParquetBarCache,
)
from tyche.adapters.data.yfinance_source import SOURCE_NAME
from tyche.config import TycheConfig
from tyche.core.backtest import (
    BacktestMetrics,
    BacktestResult,
    BacktestSpec,
    Drawdown,
    MetricsError,
    SeriesMetrics,
    measure_backtest,
    run_backtest,
)
from tyche.core.backtest.metrics import DAYS_PER_YEAR, RISK_FREE_RATE, SESSIONS_PER_YEAR
from tyche.core.domain import AssetClass, BarHistory, Currency, Money, PriceAdjustment
from tyche.core.ports import Calendar, Clock
from tyche.runtime.data import CALENDAR_START
from tyche.runtime.strategies import build_strategies

RECORD_FORMAT = 1
"""Version of ``run.json``'s layout. Raised when a field changes meaning or goes away."""

METRICS_FORMAT = 1
"""Version of ``metrics.json``'s layout. Raised when a field changes meaning or goes away."""

FRACTION_PLACES = Decimal("0.000001")
"""Fractions and ratios in ``metrics.json`` are rounded to six decimal places."""

CALENDAR_MARGIN = timedelta(days=31)
"""How far past the last day the calendar is loaded: settlement looks a session ahead."""


class BacktestRequestError(ValueError):
    """The backtest cannot run as asked: data not cached, a date out of range."""


@dataclass(frozen=True, slots=True)
class CodeVersion:
    """Which code ran.

    Attributes:
        tyche: The package version.
        commit: The git commit of the checkout Tyche runs from, or ``None`` when it
            is not running from a git checkout.
        dirty: True if that checkout had uncommitted changes, so the commit alone
            does not reproduce the run.
    """

    tyche: str
    commit: str | None
    dirty: bool

    def __str__(self) -> str:
        if self.commit is None:
            return self.tyche
        return f"{self.tyche}+g{self.commit[:12]}{'.dirty' if self.dirty else ''}"


GitRunner = Callable[[Sequence[str]], str | None]
"""Runs ``git`` with the given arguments and returns its output, or ``None`` on failure."""


def _git(arguments: Sequence[str]) -> str | None:
    folder = Path(__file__).resolve().parent
    try:
        completed = subprocess.run(
            ["git", "-C", str(folder), *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return completed.stdout if completed.returncode == 0 else None


def current_code_version(git: GitRunner = _git) -> CodeVersion:
    """The package version, plus the git commit and whether the checkout is dirty."""
    head = git(["rev-parse", "HEAD"])
    if head is None or not head.strip():
        return CodeVersion(__version__, None, False)
    # Uncommitted changes to tracked files anywhere, or new files in the source tree.
    changed = git(["status", "--porcelain", "--untracked-files=no"])
    untracked = git(["ls-files", "--others", "--exclude-standard", "--", ":/src"])
    dirty = bool(changed and changed.strip()) or bool(untracked and untracked.strip())
    return CodeVersion(__version__, head.strip(), dirty)


@dataclass(frozen=True, slots=True)
class BacktestOutcome:
    """A finished backtest, how it measured up, and where its record was written.

    ``metrics`` is ``None`` only when the run could not be measured, such as a run that
    halted before its first close; ``metrics_error`` then says why.
    """

    run_id: str
    result: BacktestResult
    record_dir: Path
    code: CodeVersion
    first: date
    last: date
    metrics: BacktestMetrics | None
    metrics_error: str | None


def run_configured_backtest(
    config: TycheConfig,
    first: date,
    last: date | None = None,
    *,
    clock: Clock | None = None,
    code: CodeVersion | None = None,
) -> BacktestOutcome:
    """Backtest the workspace's strategies from ``first`` to ``last`` and record the run.

    ``last`` defaults to the day before the holdout. Reads only the cache: missing
    history raises ``BacktestRequestError`` saying what to fetch.

    Raises:
        BacktestRequestError: The request cannot be run as asked.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
        ConfigError: A strategy cannot be built from its file.
    """
    clock = clock or SystemClock()
    code = code or current_code_version()
    settings = config.backtest
    if last is None:
        last = settings.holdout_starts - timedelta(days=1)
    settings.require_before_holdout(last)
    if first < CALENDAR_START:
        raise BacktestRequestError(f"the earliest date Tyche can backtest from is {CALENDAR_START}")
    if first > last:
        raise BacktestRequestError(f"empty date range: {first} is after {last}")

    profile = config.market_profile
    built = build_strategies(config)
    calendars: dict[str, Calendar] = {
        mic: ExchangeCalendarsCalendar(mic, first=CALENDAR_START, last=last + CALENDAR_MARGIN)
        for mic in profile.calendars
    }
    cache = ParquetBarCache(config.workspace.data_dir / "bars", source=SOURCE_NAME)
    source = CacheOnlySource(SOURCE_NAME, PriceAdjustment.SPLITS)
    provider = CachedDataProvider(source, cache, calendars, clock)

    started = clock.now()
    backtests = config.workspace.reports_dir / "backtests"
    run_id = _new_run_id(backtests, started, config.config_hash)
    spec = BacktestSpec(
        run_id=run_id,
        code_version=str(code),
        config_hash=config.config_hash,
        profile=profile,
        costs=config.costs,
        strategies=built.strategies,
        budgets=built.budgets,
        settings=settings,
        first=first,
        last=last,
    )
    try:
        result = run_backtest(spec, provider, calendars)
    except NotCachedError as error:
        raise BacktestRequestError(_fetch_hint(error)) from None
    finished = clock.now()

    currency = profile.cash_currencies[0]
    metrics: BacktestMetrics | None = None
    metrics_error: str | None = None
    try:
        metrics = measure_backtest(result, currency)
    except MetricsError as error:
        metrics_error = str(error)
    record = run_record(
        config, spec, result, code, started=started, finished=finished, metrics_error=metrics_error
    )
    record_dir = backtests / run_id
    write_run_record(record_dir, record, result, currency, metrics)
    return BacktestOutcome(run_id, result, record_dir, code, first, last, metrics, metrics_error)


def _new_run_id(folder: Path, started: datetime, config_hash: str) -> str:
    base = f"{started:%Y%m%dT%H%M%SZ}-{config_hash.removeprefix('sha256:')[:8]}"
    run_id, number = base, 1
    while (folder / run_id).exists():
        number += 1
        run_id = f"{base}-{number}"
    return run_id


def _fetch_hint(error: NotCachedError) -> str:
    instrument = error.instrument
    asset_class = "" if instrument.asset_class is AssetClass.ETF else " --asset-class stock"
    return (
        f"{error}. Fetch it first:\n"
        f"  tyche data fetch {instrument.symbol} --exchange {instrument.exchange}"
        f"{asset_class} --from {error.first} --to {error.last}"
    )


# --- the record ----------------------------------------------------------------------


def _money(amount: Money) -> dict[str, str]:
    return {"amount": str(amount.amount), "currency": amount.currency.value}


def run_record(
    config: TycheConfig,
    spec: BacktestSpec,
    result: BacktestResult,
    code: CodeVersion,
    *,
    started: datetime,
    finished: datetime,
    metrics_error: str | None = None,
) -> dict[str, Any]:
    """The run record: everything needed to reproduce the run and judge what it used."""
    currency = spec.profile.cash_currencies[0]
    sessions = [s for found in result.sessions.values() for s in found]
    warm_up = [s for found in result.warm_up.values() for s in found]
    run = result.run
    plugins = {s.strategy_id: s.plugin for s in config.strategies}
    return {
        "record_format": RECORD_FORMAT,
        "run_id": spec.run_id,
        "mode": "backtest",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "code": {
            "tyche_version": code.tyche,
            "git_commit": code.commit,
            "git_dirty": code.dirty,
            "python": platform.python_version(),
        },
        "config_hash": config.config_hash,
        "market_profile": spec.profile.name,
        "range": {
            "first": spec.first.isoformat(),
            "last": spec.last.isoformat(),
            "first_session": min(s.day for s in sessions).isoformat(),
            "last_session": max(s.day for s in sessions).isoformat(),
            "sessions": len(sessions),
        },
        "warm_up": {
            "sessions_needed": result.warm_up_needed,
            "sessions": len(warm_up),
            "first": min(s.day for s in warm_up).isoformat() if warm_up else None,
        },
        "holdout_starts": spec.settings.holdout_starts.isoformat(),
        "starting_cash": _money(spec.settings.starting_cash),
        "execution": {
            "rebalance_band": str(spec.profile.execution.rebalance_band),
            "price_buffer": str(spec.profile.execution.price_buffer),
        },
        "costs_checked_on": config.costs.checked_on.isoformat(),
        "strategies": [
            {
                "id": strategy.strategy_id,
                "plugin": plugins.get(strategy.strategy_id),
                "version": strategy.version,
                "budget": str(spec.budgets[strategy.strategy_id]),
            }
            for strategy in spec.strategies
        ],
        "data": [_data_used(history) for history in result.histories],
        "benchmark": {
            "instrument": str(result.benchmark.instrument),
            "method": BENCHMARK_METHOD,
            "data": _data_used(result.benchmark),
        },
        "outcome": {
            "completed": run.completed,
            "failure": run.failure,
            "inputs": run.inputs,
            "events": run.events,
            "fills": len(result.fills),
            "free_riding": len(result.free_riding),
            "final_equity": _money(result.account.equity(currency)),
            "final_cash": _money(result.account.cash(currency).total),
            "agrees_with_broker": result.account == result.broker_account,
            "metrics": "metrics.json" if metrics_error is None else None,
            "metrics_error": metrics_error,
        },
        "config": config.snapshot,
    }


def write_run_record(
    folder: Path,
    record: dict[str, Any],
    result: BacktestResult,
    currency: Currency,
    metrics: BacktestMetrics | None = None,
) -> None:
    """Write ``run.json``, ``equity.csv``, ``fills.csv`` and ``metrics.json`` into a new
    ``folder``. Without ``metrics``, ``metrics.json`` is not written and the benchmark
    column of ``equity.csv`` is empty."""
    folder.mkdir(parents=True, exist_ok=False)
    _write_json(folder / "run.json", record)
    if metrics is not None:
        _write_json(folder / "metrics.json", metrics_record(record["run_id"], metrics))

    benchmark = {point.at: point.equity for point in metrics.benchmark_equity} if metrics else {}
    with (folder / "equity.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "close_utc",
                "equity",
                "cash",
                "settled_cash",
                "invested",
                "benchmark_equity",
                "currency",
            ]
        )
        for close in result.closes:
            account = close.account
            cash = account.cash(currency)
            bench = benchmark.get(close.as_of)
            writer.writerow(
                [
                    close.as_of.isoformat(),
                    account.equity(currency).amount,
                    cash.total.amount,
                    cash.settled.amount,
                    account.market_value(currency).amount,
                    _cents(bench) if bench is not None else "",
                    currency.value,
                ]
            )

    with (folder / "fills.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "trade_date",
                "filled_at_utc",
                "instrument",
                "side",
                "quantity",
                "price",
                "commission",
                "currency",
                "settles_on",
                "client_order_id",
                "fill_id",
            ]
        )
        for fill in result.fills:
            writer.writerow(
                [
                    fill.trade_date.isoformat(),
                    fill.filled_at.isoformat(),
                    str(fill.instrument),
                    fill.side.value,
                    fill.quantity,
                    fill.price.amount,
                    fill.commission.amount,
                    fill.price.currency.value,
                    fill.settles_on.isoformat(),
                    fill.client_order_id,
                    fill.fill_id,
                ]
            )


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _data_used(history: BarHistory) -> dict[str, Any]:
    return {
        "instrument": str(history.instrument),
        "source": SOURCE_NAME,
        "bars": len(history.bars),
        "first_bar": history.bars[0].timestamp.isoformat() if history.bars else None,
        "last_bar": history.bars[-1].timestamp.isoformat() if history.bars else None,
        "fetched_from": history.fetched[0].isoformat() if history.fetched else None,
        "fetched_to": history.fetched[1].isoformat() if history.fetched else None,
        "issues": len(history.issues),
        "distributions": len(history.distributions),
        "splits": len(history.splits),
    }


# --- the metrics ---------------------------------------------------------------------

BENCHMARK_METHOD = "total return: distributions reinvested at the ex-date close, no costs, no cash"


def _fraction(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(FRACTION_PLACES))


def _cents(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _drawdown(drawdown: Drawdown | None) -> dict[str, Any] | None:
    if drawdown is None:
        return None
    return {
        "depth": _fraction(drawdown.depth),
        "peak": drawdown.peak.isoformat(),
        "trough": drawdown.trough.isoformat(),
        "recovered": drawdown.recovered.isoformat() if drawdown.recovered else None,
    }


def _series(series: SeriesMetrics) -> dict[str, Any]:
    return {
        "first_close": series.first.isoformat(),
        "last_close": series.last.isoformat(),
        "sessions": series.sessions,
        "years": _fraction(series.years),
        "start_equity": _cents(series.start_equity),
        "end_equity": _cents(series.end_equity),
        "total_return": _fraction(series.total_return),
        "cagr": _fraction(series.cagr),
        "volatility": _fraction(series.volatility),
        "sharpe": _fraction(series.sharpe),
        "sortino": _fraction(series.sortino),
        "max_drawdown": _drawdown(series.max_drawdown),
        "exposure": _fraction(series.exposure),
    }


def metrics_record(run_id: str, metrics: BacktestMetrics) -> dict[str, Any]:
    """``metrics.json``: the run and its benchmark, measured the same way (ADR-0025).

    Fractions and ratios are strings rounded to six places (``"0.081234"`` is 8.12%);
    amounts are strings in cents. ``null`` means the figure cannot be computed.
    """
    versus = metrics.versus_benchmark
    trades = metrics.trades
    return {
        "metrics_format": METRICS_FORMAT,
        "run_id": run_id,
        "currency": metrics.currency.value,
        "conventions": {
            "sessions_per_year": SESSIONS_PER_YEAR,
            "days_per_year": str(DAYS_PER_YEAR),
            "risk_free_rate": str(RISK_FREE_RATE),
        },
        "strategy": _series(metrics.strategy),
        "benchmark": {
            "instrument": str(metrics.benchmark_instrument),
            "method": BENCHMARK_METHOD,
            **_series(metrics.benchmark),
        },
        "versus_benchmark": {
            "total_return": _fraction(versus.total_return),
            "cagr": _fraction(versus.cagr),
            "volatility": _fraction(versus.volatility),
            "sharpe": _fraction(versus.sharpe),
            "sortino": _fraction(versus.sortino),
            "max_drawdown": _fraction(versus.max_drawdown),
        },
        "trading": {
            "turnover": _fraction(metrics.turnover),
            "traded": _cents(metrics.traded.amount),
            "costs": _cents(metrics.costs.amount),
            "closed_trades": len(trades.closed),
            "wins": trades.wins,
            "win_rate": _fraction(trades.win_rate),
            "still_open": trades.still_open,
        },
    }

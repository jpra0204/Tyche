"""The backtest runner: one historical run through the whole trading path (ADR-0024).

The runner is wiring, not logic. It builds the same stages paper and live will use
(ADR-0005), swaps in the three backtest parts (``SimClock``, ``HistoricalReplay`` and
``SimBroker``), warms the stages up on the sessions before the first decision, and
hands the replay to the engine::

    check the range against the holdout
    subscribe every stage to a new bus
    load history from the warm-up start to the last day, through the DataProvider port,
        for every candidate and for the benchmark
    warm up the universe and the signals windows on the sessions before the first day
    run the engine over the replay of first..last

It does no I/O of its own: history comes through the ``DataProvider`` port, and
writing the run record is the runtime's job.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tyche.core.backtest.settings import BacktestSettings
from tyche.core.domain import (
    Account,
    BarHistory,
    Currency,
    Fill,
    MarketProfile,
    MoneyLimits,
    Session,
    TradingCosts,
)
from tyche.core.engine import Engine, RunResult
from tyche.core.events import AccountEvent, EventBus, FillEvent, RunMode
from tyche.core.pipeline.execution import AccountState, ExecutionStage, SleeveBook
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.portfolio import PortfolioStage
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage, Strategy
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.ports import Calendar, DataProvider, OutOfCalendarRangeError
from tyche.core.risk import RiskGate, RiskLimits
from tyche.core.sim import FreeRidingViolation, HistoricalReplay, SimBroker, SimClock


class BacktestError(Exception):
    """The backtest cannot run as asked, for example a range with no sessions."""


@dataclass(frozen=True, slots=True)
class BacktestSpec:
    """Everything one backtest run is made of.

    Attributes:
        run_id: Identifies the run in the journal and its record.
        code_version: Tyche's version and commit, recorded in the ``RunEvent``.
        config_hash: Fingerprint of the workspace configuration, when there is one.
        profile: The market profile: candidates, universe rules, execution rules.
        costs: Commissions, fees, slippage and settlement.
        strategies: The strategies to run, in the order they are asked.
        budgets: Each strategy's fraction of equity, by id.
        risk: The guardrails, the active risk profile and each strategy's own limits,
            which the risk gate applies (ADR-0033).
        money_limits: The guardrails' money caps to apply, by currency, or ``None``.
            Research backtests pass ``None``: they keep their own starting cash, and
            only paper and live trade the real account the caps describe (ADR-0034).
        settings: The starting cash and the holdout.
        first: First session day to trade.
        last: Last session day to trade. Must be before the holdout.
    """

    run_id: str
    code_version: str
    config_hash: str | None
    profile: MarketProfile
    costs: TradingCosts
    strategies: Sequence[Strategy]
    budgets: Mapping[str, Decimal]
    risk: RiskLimits
    settings: BacktestSettings
    first: date
    last: date
    money_limits: Mapping[Currency, MoneyLimits] | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """What one backtest produced.

    Attributes:
        run: How the engine run ended: completed, or the reason it halted.
        sessions: The sessions replayed, by calendar.
        warm_up: The sessions learned before the first decision, by calendar. Fewer
            than ``warm_up_needed`` when the calendar starts too late.
        warm_up_needed: Sessions of history the stages asked for.
        histories: What was loaded for each candidate, warm-up included.
        benchmark: What was loaded for the profile's benchmark, over the same days.
            The candidate's own history when the benchmark is also a candidate.
        journal: Every event of the run, in order.
        account: Tyche's own view of the account at the end.
        broker_account: The simulated broker's record of the same account.
        free_riding: Free-riding violations the broker recorded (ADR-0020).
    """

    run: RunResult
    sessions: Mapping[str, tuple[Session, ...]]
    warm_up: Mapping[str, tuple[Session, ...]]
    warm_up_needed: int
    histories: tuple[BarHistory, ...]
    benchmark: BarHistory
    journal: InMemoryJournal
    account: Account
    broker_account: Account
    free_riding: tuple[FreeRidingViolation, ...]

    @property
    def closes(self) -> list[AccountEvent]:
        """Tyche's account at every session close, oldest first: the equity curve."""
        return [envelope.event for envelope in self.journal.of_type(AccountEvent)]

    @property
    def fills(self) -> list[Fill]:
        """Every fill, in the order the broker reported them."""
        return [envelope.event.fill for envelope in self.journal.of_type(FillEvent)]


def run_backtest(
    spec: BacktestSpec, data: DataProvider, calendars: Mapping[str, Calendar]
) -> BacktestResult:
    """Run one backtest.

    Raises:
        HoldoutError: ``spec.last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
        DataError: The data provider could not supply a candidate's history.

    A run that starts and then halts (a stage failing closed) does not raise: its
    ``RunResult`` says why it stopped, and the result holds everything up to then.
    """
    spec.settings.require_before_holdout(spec.last)
    if spec.first > spec.last:
        raise BacktestError(f"empty range: {spec.first} is after {spec.last}")
    candidates = spec.profile.universe.instruments
    if not candidates:
        raise BacktestError(f"market profile {spec.profile} lists no instruments to replay")
    codes = sorted({instrument.calendar for instrument in candidates})
    unloaded = [code for code in codes if code not in calendars]
    if unloaded:
        raise BacktestError(f"no calendar loaded for {', '.join(unloaded)}")

    sessions = {code: calendars[code].sessions_between(spec.first, spec.last) for code in codes}
    empty = [code for code, found in sessions.items() if not found]
    if empty:
        raise BacktestError(f"no {', '.join(empty)} session between {spec.first} and {spec.last}")
    start = min(found[0].opens_at for found in sessions.values())
    last_close = max(found[-1].closes_at for found in sessions.values())

    clock = SimClock(start)
    bus = EventBus(clock.now)
    opening = Account.empty().deposit(spec.settings.starting_cash)
    book = SleeveBook()
    universe = UniverseStage(bus, spec.profile)
    ScreeningStage(bus, DollarVolumeScreen())
    signals = SignalsStage(bus, spec.strategies, positions=book)
    PortfolioStage(bus, spec.budgets)
    state = AccountState(bus, opening)
    RiskGate(bus, spec.risk, book, spec.money_limits)
    ExecutionStage(bus, book, spec.costs, calendars, spec.profile.execution, spec.money_limits)
    broker = SimBroker(bus, opening, spec.costs, calendars)
    journal = InMemoryJournal(bus)

    needed = max(universe.history_needed, *signals.history_needed.values())
    warm_up = {
        code: _sessions_before(calendars[code], sessions[code][0].day, needed) for code in codes
    }
    load_from = min(
        (found[0].day for found in warm_up.values() if found),
        default=spec.first,
    )
    histories = tuple(data.daily_bars(i, load_from, spec.last) for i in candidates)
    by_instrument = {history.instrument: history for history in histories}
    if spec.profile.benchmark in by_instrument:
        benchmark = by_instrument[spec.profile.benchmark]
    else:
        benchmark = data.daily_bars(spec.profile.benchmark, load_from, spec.last)
    for history in (*histories, benchmark):
        late = [bar for bar in history.bars if bar.timestamp > last_close]
        if late:
            raise BacktestError(
                f"the data provider returned {history.instrument} bars after "
                f"{spec.last}, up to {late[-1].timestamp.isoformat()}; refusing to run so "
                "that no data beyond the range, and so none of the holdout, can be seen"
            )
    first_close = min(found[0].closes_at for found in sessions.values())
    if not any(bar.timestamp <= first_close for bar in benchmark.bars):
        raise BacktestError(
            f"no bar of the benchmark {benchmark.instrument} on or before {spec.first}; "
            "the benchmark is measured from the first session's close"
        )

    universe.warm_up(histories, warm_up)
    signals.warm_up(histories, through=start)

    replay = HistoricalReplay(histories, calendars, spec.first, spec.last)
    engine = Engine(
        bus,
        clock,
        run_id=spec.run_id,
        mode=RunMode.BACKTEST,
        code_version=spec.code_version,
        config_hash=spec.config_hash,
    )
    run = engine.run(replay)
    return BacktestResult(
        run=run,
        sessions=sessions,
        warm_up=warm_up,
        warm_up_needed=needed,
        histories=histories,
        benchmark=benchmark,
        journal=journal,
        account=state.account,
        broker_account=broker.account(),
        free_riding=broker.free_riding,
    )


def _sessions_before(calendar: Calendar, day: date, count: int) -> tuple[Session, ...]:
    """Up to ``count`` sessions before ``day``, oldest first; fewer if the calendar ends."""
    found: list[Session] = []
    before = day
    while len(found) < count:
        try:
            session = calendar.previous_session(before)
        except OutOfCalendarRangeError:
            break
        found.append(session)
        before = session.day
    return tuple(reversed(found))

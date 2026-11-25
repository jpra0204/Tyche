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
    take the checkpoint the run ends in, if it completed

A run can also carry on from where an earlier one stopped (``Resume``, ADR-0038):
Tyche's stages start from that run's checkpoint and the simulator from its own state,
as paper will restart from its checkpoint with the real broker still holding the
account. The universe and the signals are warmed up exactly as for a fresh run.

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
    AccountTrigger,
    BarHistory,
    Checkpoint,
    Currency,
    Fill,
    MarketProfile,
    MoneyLimits,
    RiskRule,
    Session,
    TradingCosts,
)
from tyche.core.engine import Engine, RunResult
from tyche.core.events import AccountEvent, EventBus, FillEvent, RiskEvent, RunMode
from tyche.core.pipeline.execution import AccountState, ExecutionStage, SleeveBook
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.pipeline.portfolio import PortfolioStage
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage, Strategy
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.ports import Calendar, DataProvider, KillSwitch, OutOfCalendarRangeError
from tyche.core.risk import RiskGate, RiskLimits
from tyche.core.sim import (
    FreeRidingViolation,
    HistoricalReplay,
    SimBroker,
    SimBrokerState,
    SimClock,
)


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
class Resume:
    """Where a backtest carries on from: an earlier run's end (ADR-0038).

    Attributes:
        checkpoint: Tyche's state when the earlier run ended. Replaces the starting
            cash: the account is the checkpoint's.
        broker: The simulator's own state at the same moment, standing in for the
            real broker, which keeps the account while Tyche is stopped.
    """

    checkpoint: Checkpoint
    broker: SimBrokerState


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
        checkpoint: The state the run ended in, for a run that completed; ``None`` for
            one that halted, whose state cannot be trusted (ADR-0038).
        broker_state: The simulator's own state at the end, with the checkpoint.
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
    checkpoint: Checkpoint | None = None
    broker_state: SimBrokerState | None = None

    @property
    def closes(self) -> list[AccountEvent]:
        """Tyche's account at every session close, oldest first: the equity curve."""
        return [envelope.event for envelope in self.journal.of_type(AccountEvent)]

    @property
    def fills(self) -> list[Fill]:
        """Every fill, in the order the broker reported them."""
        return [envelope.event.fill for envelope in self.journal.of_type(FillEvent)]

    @property
    def triggers(self) -> list[AccountTrigger]:
        """Every account rule that reached its limit, oldest first (ADR-0035)."""
        return [
            envelope.event.adjustment
            for envelope in self.journal.of_type(RiskEvent)
            if isinstance(envelope.event.adjustment, AccountTrigger)
        ]

    @property
    def halt(self) -> AccountTrigger | None:
        """The drawdown kill that halted trading, or ``None``. A halted run still runs
        to its last day, sending no order (ADR-0035)."""
        return next((t for t in self.triggers if t.rule is RiskRule.DRAWDOWN_KILL), None)


def run_backtest(
    spec: BacktestSpec,
    data: DataProvider,
    calendars: Mapping[str, Calendar],
    *,
    resume: Resume | None = None,
    kill_switch: KillSwitch | None = None,
) -> BacktestResult:
    """Run one backtest, from the starting cash or carrying on from ``resume``.

    ``kill_switch`` is read by the risk gate at every decision, as in paper and live
    (ADR-0039). Backtest commands give none: the workspace's ``KILL`` file stops
    trading, not research. Tests give one to prove what an engaged switch does.

    Raises:
        HoldoutError: ``spec.last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run, or ``resume`` was taken
            after the first session opens.
        DataError: The data provider could not supply a candidate's history.

    A run that starts and then halts (a stage failing closed) does not raise: its
    ``RunResult`` says why it stopped, and the result holds everything up to then.
    The drawdown kill is not such a halt: it stops trading, not the run, which goes on
    to its last day with every holding kept and no order sent (``BacktestResult.halt``).
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

    if resume is not None and resume.checkpoint.saved_at >= start:
        raise BacktestError(
            f"cannot carry on from {resume.checkpoint.run_id}'s checkpoint, taken at "
            f"{resume.checkpoint.saved_at.isoformat()}, in a run whose first session opens "
            f"at {start.isoformat()}"
        )

    clock = SimClock(start)
    bus = EventBus(clock.now)
    universe = UniverseStage(bus, spec.profile)
    ScreeningStage(bus, DollarVolumeScreen())
    if resume is None:
        opening = Account.empty().deposit(spec.settings.starting_cash)
        book = SleeveBook()
    else:
        opening = resume.checkpoint.account
        book = SleeveBook(resume.checkpoint.sleeves)
    signals = SignalsStage(bus, spec.strategies, positions=book)
    PortfolioStage(bus, spec.budgets)
    state = AccountState(bus, opening)
    gate = RiskGate(
        bus,
        spec.risk,
        book,
        spec.money_limits,
        rules=resume.checkpoint.rules if resume else None,
        kill_switch=kill_switch,
    )
    execution = ExecutionStage(
        bus,
        book,
        spec.costs,
        calendars,
        spec.profile.execution,
        spec.money_limits,
        start=resume.checkpoint.execution if resume else None,
    )
    if resume is None:
        broker = SimBroker(bus, opening, spec.costs, calendars)
    else:
        broker = SimBroker.resume(bus, resume.broker, spec.costs, calendars)
    journal = InMemoryJournal(bus)

    needed = max(universe.history_needed, *signals.history_needed.values())
    warm_up = {
        code: sessions_before(calendars[code], sessions[code][0].day, needed) for code in codes
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
    checkpoint = None
    if run.completed:
        checkpoint = Checkpoint(
            run_id=spec.run_id,
            saved_at=clock.now(),
            code_version=spec.code_version,
            config_hash=spec.config_hash,
            account=state.account,
            sleeves=book.state(),
            execution=execution.state(),
            rules=gate.rules_state(),
        )
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
        checkpoint=checkpoint,
        broker_state=broker.state() if run.completed else None,
    )


def sessions_before(calendar: Calendar, day: date, count: int) -> tuple[Session, ...]:
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

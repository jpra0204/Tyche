"""Wiring for ``tyche paper run``: one decision cycle on the IBKR paper account (ADR-0045).

Composition-root code (ADR-0004). The core gains no paper-only code: this module builds
the same stages a backtest builds, with the wall clock, the daily feed and
``IBKRBroker`` in place of the simulator's three parts (ADR-0005), and runs them in the
order ADR-0045 sets. A cycle is recorded as two runs in the state database, each with
its journal and its checkpoint:

1. **The check**, ``paper-<time>-check``. Connect; read IBKR (``sync``): fills since the
   last run reach Tyche's account, its sleeves and execution, which places the stop of
   each entry that filled. Reconcile with IBKR's record (ADR-0044), correct, save. On
   the first run there is no checkpoint: Tyche starts from IBKR's cash in an account
   that must hold nothing else.
2. **The decision**, ``paper-<time>``, only when a session has closed since the last
   decision. The stages are built again from the checkpoint the check saved, so the
   gate sees any reconciliation halt it stored. Warm up; run the engine over the daily
   feed (ADR-0043); wait for IBKR to confirm stop cancellations so no sale goes out
   beside a stop on the same shares; reconcile again; save.

Saving the check first keeps what it read: IB Gateway reports only today's executions,
so fills read and then lost to a failed decision could not be read again.

A run that fails at any step saves no checkpoint for that step, disconnects, and sends
``run_failed_alert``. Every other alert is collected during the run and sent after it
(ADR-0040).
"""

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from tyche.adapters.brokers.ibkr import IbAsyncClient, IBClient, IBKRBroker
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.clocks import SystemClock
from tyche.adapters.data import (
    BarSource,
    CachedDataProvider,
    ParquetBarCache,
    YFinanceSource,
    yfinance_fetcher,
)
from tyche.adapters.kill_switch import FlagFileKillSwitch
from tyche.adapters.storage import (
    SqliteBrokerOrderStore,
    SqliteCheckpointStore,
    SqliteJournalStore,
    open_database,
)
from tyche.config import EnvFileError, IbkrConnection, TycheConfig, ibkr_connection, load_secrets
from tyche.core.backtest import sessions_before
from tyche.core.domain import (
    Account,
    AccountRulesState,
    Checkpoint,
    ExecutionState,
    Reconciliation,
    ReconciliationState,
    ReconciliationStatus,
    Session,
    SleeveState,
)
from tyche.core.engine import Engine
from tyche.core.events import (
    CycleSkippedEvent,
    EventBus,
    ReconciliationEvent,
    RunEvent,
    RunMode,
    RunStage,
)
from tyche.core.feeds import DailyFeed
from tyche.core.pipeline.alerts import (
    AlertCollector,
    orders_alert,
    run_failed_alert,
    stopped_alert,
)
from tyche.core.pipeline.execution import AccountState, ExecutionStage, SleeveBook
from tyche.core.pipeline.journal import StoredJournal
from tyche.core.pipeline.portfolio import PortfolioStage
from tyche.core.pipeline.reconciliation import correct, reconcile
from tyche.core.pipeline.screening import DollarVolumeScreen, ScreeningStage
from tyche.core.pipeline.signals import SignalsStage
from tyche.core.pipeline.universe import UniverseStage
from tyche.core.ports import Alert, Calendar, PacedClock
from tyche.core.risk import RiskGate
from tyche.runtime.data import CALENDAR_START, followed_instruments
from tyche.runtime.notify import Delivery, build_notifier, deliver
from tyche.runtime.strategies import build_strategies

SOURCE = "paper"
"""The ``source`` of the envelopes the paper cycle publishes itself."""

CANCEL_WAIT = timedelta(seconds=60)
"""How long a held sale waits for IBKR to confirm its stop's cancellation (ADR-0045)."""

POLL_SECONDS = 1.0
"""Seconds between two reads of IBKR while a sale waits."""

CALENDAR_MARGIN = timedelta(days=31)
"""How far past today the calendar is loaded: the next open, and settlement, look ahead."""

FORGOTTEN = "ended: IBKR no longer lists it and reconciliation dropped it from Tyche's records"
"""The note on an order the adapter's store closes once reconciliation dropped it."""

NOT_CONFIRMED = "its stop's cancellation was not confirmed by IBKR in time (ADR-0045)"

Sleep = Callable[[float], None]

_log = logging.getLogger(__name__)


class PaperRunError(Exception):
    """The paper cycle cannot run as things are. Never contains a secret."""


@dataclass(frozen=True, slots=True)
class PaperOutcome:
    """One paper cycle: what it read, decided and recorded.

    Attributes:
        check_run: The check's run id.
        decision_run: The decision's run id, or ``None`` when no session had closed
            since the last decision.
        first_run: True when there was no checkpoint, and Tyche started from IBKR's cash.
        startup: The reconciliation at startup, once IBKR was read.
        after: The reconciliation after the decision, if one ran.
        sessions: The sessions the decision published, oldest first.
        traded: The session whose decision ran, if one did.
        skipped: Decisions skipped: too late, or a candidate without a bar.
        lost: Orders lost while sending, now rejected and never resent.
        not_sent: Sales rejected unsent because a stop's cancellation was not confirmed.
        checkpoint: The last checkpoint saved, or ``None`` if the cycle saved none.
        alerts: Every alert of the cycle, in the order sent.
        delivery: What became of them.
        failure: Why the cycle stopped, if it did; then ``completed`` is False.
    """

    check_run: str
    decision_run: str | None = None
    first_run: bool = False
    startup: Reconciliation | None = None
    after: Reconciliation | None = None
    sessions: tuple[Session, ...] = ()
    traded: Session | None = None
    skipped: tuple[CycleSkippedEvent, ...] = ()
    lost: tuple[str, ...] = ()
    not_sent: tuple[str, ...] = ()
    checkpoint: Checkpoint | None = None
    alerts: tuple[Alert, ...] = ()
    delivery: Delivery = field(default_factory=Delivery)
    failure: str | None = None

    @property
    def completed(self) -> bool:
        return self.failure is None


@dataclass
class _Progress:
    """What the cycle has done so far, kept so a failure can still report it."""

    check_run: str
    decision_run: str | None = None
    first_run: bool = False
    startup: Reconciliation | None = None
    after: Reconciliation | None = None
    sessions: tuple[Session, ...] = ()
    traded: Session | None = None
    skipped: tuple[CycleSkippedEvent, ...] = ()
    lost: list[str] = field(default_factory=list)
    not_sent: list[str] = field(default_factory=list)
    foreign_executions: int = 0
    checkpoint: Checkpoint | None = None
    alerts: list[Alert] = field(default_factory=list)


def run_paper(
    config: TycheConfig,
    *,
    environ: Mapping[str, str],
    code_version: str,
    clock: PacedClock | None = None,
    client: IBClient | None = None,
    source: BarSource | None = None,
    sleep: Sleep = time.sleep,
) -> PaperOutcome:
    """Run one paper cycle and send its alerts.

    Args:
        config: The workspace's configuration, with the risk profile to trade under.
        environ: The process environment: secrets set there override ``.env``.
        code_version: Recorded with every run, and in every alert.
        clock: The wall clock; tests give a fake.
        client: The connection to IB Gateway; ``IbAsyncClient`` by default.
        source: Where bars missing from the cache come from; Yahoo by default.
        sleep: How to wait between two reads of IBKR; tests give a fake.

    Raises:
        PaperRunError: ``.env`` lacks the IB Gateway connection, so nothing could start
            and no alert can be trusted to reach anyone but the terminal.

    Any failure after that is returned, not raised: ``failure`` says why, and the
    failure is alerted.
    """
    clock = clock or SystemClock()
    try:
        secrets = load_secrets(config.workspace.env_file, environ)
        connection = ibkr_connection(secrets)
    except EnvFileError as error:
        raise PaperRunError(str(error)) from None
    notifier = build_notifier(secrets, code_version=code_version)
    started = clock.now()
    progress = _Progress(check_run=f"paper-{started:%Y%m%dT%H%M%SZ}-check")
    cycle = _Cycle(
        config,
        connection,
        clock=clock,
        client=client or IbAsyncClient(),
        source=source,
        code_version=code_version,
        sleep=sleep,
    )
    failure: str | None = None
    try:
        cycle.run(progress, started)
    except Exception as error:  # any failure must be alerted, then reported
        text = (
            str(error) if isinstance(error, PaperRunError) else f"{type(error).__name__}: {error}"
        )
        failure = _without_secrets(text, secrets.values())
        _log.exception("paper run failed", extra={"fields": {"run_id": progress.check_run}})
    finally:
        cycle.close()

    alerts = list(progress.alerts)
    orders = orders_alert(
        clock.now(),
        lost=progress.lost,
        not_sent=progress.not_sent,
        foreign_executions=progress.foreign_executions,
    )
    if orders is not None:
        alerts.append(orders)
    if failure is not None:
        run_id = progress.decision_run or progress.check_run
        alerts.append(run_failed_alert(run_id, RunMode.PAPER, failure, clock.now()))
    delivery = deliver(notifier, alerts)
    return PaperOutcome(
        check_run=progress.check_run,
        decision_run=progress.decision_run,
        first_run=progress.first_run,
        startup=progress.startup,
        after=progress.after,
        sessions=progress.sessions,
        traded=progress.traded,
        skipped=progress.skipped,
        lost=tuple(progress.lost),
        not_sent=tuple(progress.not_sent),
        checkpoint=progress.checkpoint,
        alerts=tuple(alerts),
        delivery=delivery,
        failure=failure,
    )


class _Cycle:
    """The cycle's parts, shared by the check and the decision."""

    def __init__(
        self,
        config: TycheConfig,
        connection: IbkrConnection,
        *,
        clock: PacedClock,
        client: IBClient,
        source: BarSource | None,
        code_version: str,
        sleep: Sleep,
    ) -> None:
        self._config = config
        self._connection = connection
        self._clock = clock
        self._client = client
        self._source = source
        self._code_version = code_version
        self._sleep = sleep
        profile = config.market_profile
        if len(profile.calendars) != 1:
            raise PaperRunError(
                f"the paper cycle follows one calendar for now; market profile {profile} "
                f"has {len(profile.calendars)}"
            )
        (self._mic,) = profile.calendars
        last = clock.now().date() + CALENDAR_MARGIN
        self._calendar: Calendar = ExchangeCalendarsCalendar(
            self._mic, first=CALENDAR_START, last=last
        )
        self._calendars: Mapping[str, Calendar] = {self._mic: self._calendar}
        self._instruments = followed_instruments(profile)
        self._database: sqlite3.Connection | None = None
        self._brokers: list[IBKRBroker] = []

    # --- the cycle ---------------------------------------------------------------------

    def run(self, progress: _Progress, started: datetime) -> None:
        self._database = open_database(self._config.workspace.state_database)
        checkpoints = SqliteCheckpointStore(self._database)
        latest = checkpoints.latest()
        if latest is None:
            progress.first_run = True
            latest = self._first_checkpoint(progress.check_run)
            _log.warning("first paper run: starting from IBKR's cash")

        checked = self._check(progress, latest)
        checkpoints.save(checked)
        progress.checkpoint = checked

        first = self._first_session(checked, started)
        if first is None:
            _log.info("no session has closed since the last decision; nothing to decide")
            return
        progress.decision_run = f"paper-{started:%Y%m%dT%H%M%SZ}"
        decided = self._decide(progress, checked, first)
        if decided is None:
            progress.decision_run = None  # nothing was published under it
            return
        checkpoints.save(decided)
        progress.checkpoint = decided

    def close(self) -> None:
        """Disconnect every broker and close the state database. Never raises."""
        for broker in self._brokers:
            try:
                broker.close()
            except Exception:  # closing must not hide the run's own outcome
                _log.warning("could not disconnect from IB Gateway cleanly")
        self._brokers.clear()
        if self._database is not None:
            self._database.close()
            self._database = None

    # --- step 1: the check -------------------------------------------------------------

    def _check(self, progress: _Progress, base: Checkpoint) -> Checkpoint:
        """Read IBKR into Tyche's records, reconcile, correct (ADR-0044)."""
        run_id = progress.check_run
        bus = EventBus(self._clock.now)
        StoredJournal(bus, SqliteJournalStore(self._db), run_id)
        collector = AlertCollector(bus)
        book = SleeveBook(base.sleeves)
        state = AccountState(bus, base.account)
        execution = self._execution(bus, book, base)
        broker = self._broker(bus)

        self._announce(bus, run_id, RunStage.STARTED)
        broker.connect()
        self._read(broker, progress)
        snapshot = Checkpoint(
            run_id=run_id,
            saved_at=self._clock.now(),
            code_version=self._code_version,
            config_hash=self._config.config_hash,
            account=state.account,
            sleeves=book.state(),
            execution=execution.state(),
            rules=base.rules,
            reconciliation=base.reconciliation,
        )
        found, checked = self._reconcile(bus, broker, snapshot)
        progress.startup = found
        self._announce(bus, run_id, RunStage.COMPLETED)
        broker.close()
        progress.alerts.extend(collector.alerts())

        standing = checked.rules.halt is not None or checked.reconciliation.halt is not None
        if standing and found.status is not ReconciliationStatus.MISMATCH:
            progress.alerts.append(
                stopped_alert(
                    self._clock.now(),
                    halt=checked.rules.halt,
                    unreconciled=checked.reconciliation.halt,
                )
            )
        return checked

    def _first_checkpoint(self, run_id: str) -> Checkpoint:
        """Tyche's starting state on the first run: IBKR's cash, nothing else (ADR-0045).

        Raises:
            PaperRunError: IBKR holds a position or a working order, or no cash in the
                currencies the profile trades in. Tyche cannot know which sleeve a
                position belongs to, nor what stop protects it.
        """
        store = SqliteBrokerOrderStore(self._db)
        probe = IBKRBroker(
            EventBus(self._clock.now),
            self._client,
            store,
            connection=self._connection,
            instruments=self._instruments,
            calendars=self._calendars,
            settlement_days=self._config.costs.settlement_days,
            clock=self._clock,
        )
        self._brokers.append(probe)
        probe.connect()
        record = probe.record()
        probe.close()

        found: list[str] = []
        if record.account.positions:
            held = ", ".join(f"{p.quantity} {p.instrument}" for p in record.account.positions)
            found.append(f"positions ({held})")
        working = len(record.orders) + record.foreign_orders
        if working:
            found.append(f"{working} working order(s)")
        unfinished = store.unfinished()
        if unfinished and not record.orders:
            found.append(f"{len(unfinished)} order(s) Tyche sent with no checkpoint saved")
        if found:
            raise PaperRunError(
                "the first paper run needs an account holding nothing but cash, and IBKR "
                f"reports {' and '.join(found)}; Tyche cannot tell which strategy owns a "
                "position or which stop protects it. Close them in IBKR's app, then run "
                "again (ADR-0045)"
            )
        account = Account.empty()
        currencies = self._config.market_profile.cash_currencies
        for currency in currencies:
            account = account.with_cash(record.account.cash(currency))
        if all(account.cash(c).total.is_zero for c in currencies):
            named = ", ".join(str(c) for c in currencies)
            raise PaperRunError(
                f"the paper account holds no {named} cash, and the profile trades only in "
                f"{named}; fund it in that currency first"
            )
        return Checkpoint(
            run_id=run_id,
            saved_at=self._clock.now(),
            code_version=self._code_version,
            config_hash=self._config.config_hash,
            account=account,
            sleeves=SleeveState(),
            execution=ExecutionState(),
            rules=AccountRulesState(),
            reconciliation=ReconciliationState(),
        )

    # --- step 2: the decision ----------------------------------------------------------

    def _decide(self, progress: _Progress, base: Checkpoint, first: date) -> Checkpoint | None:
        """Decide on every session closed since the last decision, and send the orders."""
        run_id = progress.decision_run
        assert run_id is not None  # set by run() just before
        config = self._config
        profile = config.market_profile
        strategies = build_strategies(config)

        bus = EventBus(self._clock.now)
        StoredJournal(bus, SqliteJournalStore(self._db), run_id)
        collector = AlertCollector(bus)
        universe = UniverseStage(bus, profile)
        ScreeningStage(bus, DollarVolumeScreen())
        book = SleeveBook(base.sleeves)
        signals = SignalsStage(bus, strategies.strategies, positions=book)
        PortfolioStage(bus, strategies.budgets)
        state = AccountState(bus, base.account)
        gate = RiskGate(
            bus,
            config.risk_limits,
            book,
            config.risk_limits.guardrails.money_limits(),
            rules=base.rules,
            kill_switch=FlagFileKillSwitch(config.workspace.kill_file),
            unreconciled=base.reconciliation.halt,
        )
        execution = self._execution(bus, book, base)
        broker = self._broker(bus)

        latest = self._latest_final_session()
        if latest is None or latest.day < first:
            return None
        needed = max(universe.history_needed, *signals.history_needed.values())
        warm_up = sessions_before(self._calendar, first, needed)
        load_from = warm_up[0].day if warm_up else first
        provider = self._provider()
        candidates = profile.universe.instruments
        histories = tuple(provider.daily_bars(i, load_from, latest.day) for i in candidates)
        if profile.benchmark not in candidates:
            provider.daily_bars(profile.benchmark, load_from, latest.day)  # kept current

        feed = DailyFeed(histories, self._calendar, self._clock, profile.daily_cycle, first)
        if not feed.sessions or feed.starts_at is None:
            return None
        universe.warm_up(histories, {self._mic: warm_up})
        signals.warm_up(histories, through=feed.starts_at)

        broker.connect()
        engine = Engine(
            bus,
            self._clock,
            run_id=run_id,
            mode=RunMode.PAPER,
            code_version=self._code_version,
            config_hash=config.config_hash,
        )
        result = engine.run(feed)
        progress.sessions = feed.sessions
        progress.traded = feed.traded
        progress.skipped = feed.skipped
        if not result.completed:
            progress.alerts.extend(collector.alerts())
            raise PaperRunError(f"the decision run halted: {result.failure}")

        self._read(broker, progress)
        snapshot = Checkpoint(
            run_id=run_id,
            saved_at=self._clock.now(),
            code_version=self._code_version,
            config_hash=config.config_hash,
            account=state.account,
            sleeves=book.state(),
            execution=execution.state(),
            rules=gate.rules_state(),
            reconciliation=base.reconciliation,
        )
        found, decided = self._reconcile(bus, broker, snapshot)
        progress.after = found
        broker.close()
        progress.alerts.extend(collector.alerts())
        return decided

    # --- shared steps ------------------------------------------------------------------

    def _read(self, broker: IBKRBroker, progress: _Progress) -> None:
        """Read IBKR, send held sales once their stops' cancellations are confirmed,
        and reject those still waiting after ``CANCEL_WAIT`` (ADR-0045)."""
        deadline = self._clock.now() + CANCEL_WAIT
        report = broker.sync()
        progress.lost.extend(report.lost)
        progress.foreign_executions = max(progress.foreign_executions, report.foreign_executions)
        while broker.release():
            if self._clock.now() >= deadline:
                progress.not_sent.extend(broker.reject_held(NOT_CONFIRMED))
                break
            self._sleep(POLL_SECONDS)
            report = broker.sync()
            progress.lost.extend(report.lost)
        else:
            broker.sync()  # the orders just sent, as IBKR now lists them

    def _reconcile(
        self, bus: EventBus, broker: IBKRBroker, snapshot: Checkpoint
    ) -> tuple[Reconciliation, Checkpoint]:
        """Compare, journal, correct; then close the adapter's records of orders that
        reconciliation dropped (ADR-0044)."""
        found = reconcile(
            snapshot,
            broker.record(),
            self._config.market_profile.reconciliation,
            self._config.market_profile.cash_currencies,
            self._clock.now(),
            calendars=self._calendars,
        )
        bus.publish(ReconciliationEvent(found), source=SOURCE)
        bus.drain()
        corrected = correct(snapshot, found)
        expected = {o.state.order.client_order_id for o in corrected.execution.orders}
        tracked = {u.client_order_id for u in broker.last_report.unaccounted}
        broker.forget(tracked - expected, FORGOTTEN)
        _log.info(
            "reconciled",
            extra={"fields": {"run_id": snapshot.run_id, "status": str(found.status)}},
        )
        return found, corrected

    def _execution(self, bus: EventBus, book: SleeveBook, base: Checkpoint) -> ExecutionStage:
        return ExecutionStage(
            bus,
            book,
            self._config.costs,
            self._calendars,
            self._config.market_profile.execution,
            self._config.risk_limits.guardrails.money_limits(),
            start=base.execution,
        )

    def _broker(self, bus: EventBus) -> IBKRBroker:
        broker = IBKRBroker(
            bus,
            self._client,
            SqliteBrokerOrderStore(self._db),
            connection=self._connection,
            instruments=self._instruments,
            calendars=self._calendars,
            settlement_days=self._config.costs.settlement_days,
            clock=self._clock,
        )
        self._brokers.append(broker)
        return broker

    def _provider(self) -> CachedDataProvider:
        data_dir = self._config.workspace.data_dir
        source = self._source or YFinanceSource(
            self._calendars, fetch=yfinance_fetcher(data_dir / "yfinance-cache")
        )
        return CachedDataProvider(
            source,
            ParquetBarCache(data_dir / "bars", source=source.name),
            self._calendars,
            self._clock,
            after_close=self._config.market_profile.daily_cycle.after_close,
        )

    def _first_session(self, checkpoint: Checkpoint, now: datetime) -> date | None:
        """The first session not yet decided on: the one after the last close measured,
        or the latest final session on a first run. ``None`` if it has not closed yet."""
        latest = self._latest_final_session(now)
        if latest is None:
            return None
        last_close = checkpoint.rules.last_close
        if last_close is None:
            return latest.day
        following = self._calendar.next_session(last_close.date())
        return following.day if following.day <= latest.day else None

    def _latest_final_session(self, now: datetime | None = None) -> Session | None:
        """The latest session whose bars count as final (ADR-0043), or ``None``."""
        moment = now or self._clock.now()
        rules = self._config.market_profile.daily_cycle
        recent = self._calendar.sessions_between(moment.date() - timedelta(days=14), moment.date())
        final = [s for s in recent if rules.ready_at(s) <= moment]
        return final[-1] if final else None

    def _announce(self, bus: EventBus, run_id: str, stage: RunStage) -> None:
        bus.publish(
            RunEvent(
                run_id=run_id,
                mode=RunMode.PAPER,
                stage=stage,
                code_version=self._code_version,
                config_hash=self._config.config_hash,
            ),
            source=SOURCE,
        )
        bus.drain()

    @property
    def _db(self) -> sqlite3.Connection:
        if self._database is None:  # pragma: no cover - run() opens it first
            raise PaperRunError("the state database is not open")
        return self._database


def _without_secrets(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text

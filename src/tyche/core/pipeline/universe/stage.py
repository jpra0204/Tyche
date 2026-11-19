"""UniverseStage: pipeline stage 1, which instruments are eligible at each decision time.

The stage builds its own view of the market from the events it has been sent: the last
few bars of each instrument and the data issues reported about it. It never asks a data
provider, so it cannot know anything the feed has not published yet. That is what keeps
it free of lookahead in a backtest, and identical in paper and live (ADR-0005).

At each ``DataReadyEvent`` every instrument the feed expected is checked against the
market profile's ``UniverseRules``, in this order, and the first rule it fails is its
reason for exclusion:

1. **In the profile**: its calendar is one of the profile's, it is quoted in the
   currency of the thresholds, and its asset class is allowed.
2. **Has a bar**: there is a bar for this decision time.
3. **Clean data**: no disqualifying data issue (``DISQUALIFYING_ISSUES``) was reported
   about it in this cycle or the previous ``quality_sessions - 1`` cycles (ADR-0018).
4. **Enough history**: it has at least ``liquidity_sessions`` bars so far.
5. **Price**: its last close is at least ``min_price``.
6. **Liquidity**: the mean of close times volume over its last ``liquidity_sessions``
   bars is at least ``min_average_dollar_volume``.

The result is one ``UniverseEvent`` per cycle, in which every expected instrument
appears once, as eligible or as excluded with its reason.

Two limits worth knowing:

* The universe can only choose among the instruments the feed was given. Yahoo lists
  only companies that still exist, so a backtest over today's symbols starts from the
  survivors (survivorship bias).
* A bar missing more than ``quality_sessions`` cycles ago is no longer held against an
  instrument, and its liquidity average then spans a few more sessions than
  ``liquidity_sessions``.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from tyche.core.domain import (
    DISQUALIFYING_ISSUES,
    Bar,
    BarHistory,
    DataIssue,
    Exclusion,
    ExclusionReason,
    Instrument,
    MarketProfile,
    Session,
    Timeframe,
    UniverseMember,
)
from tyche.core.events import (
    BarEvent,
    DataQualityEvent,
    DataReadyEvent,
    Envelope,
    EventBus,
    UniverseEvent,
)

SUBSCRIBER = "universe"


class UniverseError(Exception):
    """The inputs broke an assumption the stage relies on. A bug, not a market event."""


@dataclass(slots=True)
class _Quarantine:
    """An instrument kept out after a data issue, and for how many more cycles."""

    issue: DataIssue
    cycles_left: int


class UniverseStage:
    """Pipeline stage 1. Publishes a ``UniverseEvent`` for every ``DataReadyEvent``.

    Subscribe it before anything is published, like every other component, and call
    ``warm_up`` before the first event if the first decision should be judged on the
    sessions before it.

    Args:
        bus: The run's event bus.
        profile: The market profile, whose ``universe`` rules are applied.

    Only daily data is handled in Phase 1: a bar or a ``DataReadyEvent`` of another
    timeframe halts the run rather than being mixed into daily averages.
    """

    def __init__(self, bus: EventBus, profile: MarketProfile) -> None:
        self._bus = bus
        self._profile = profile
        self._rules = profile.universe
        self._min_price = float(self._rules.min_price.amount)
        self._min_dollar_volume = float(self._rules.min_average_dollar_volume.amount)
        self._bars: dict[Instrument, deque[Bar]] = {}
        self._quarantine: dict[Instrument, _Quarantine] = {}
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)
        bus.subscribe(DataQualityEvent, self._on_issue, name=SUBSCRIBER)
        bus.subscribe(DataReadyEvent, self._on_ready, name=SUBSCRIBER)

    @property
    def history_needed(self) -> int:
        """Sessions the stage must have seen to judge as it would in the middle of a run.

        Enough for the liquidity average, and enough to remember a data problem that
        would still keep an instrument out.
        """
        return max(self._rules.liquidity_sessions, self._rules.quality_sessions)

    def warm_up(
        self, histories: Iterable[BarHistory], sessions: Mapping[str, Sequence[Session]]
    ) -> None:
        """Learn the sessions before the run as if they had been played (ADR-0024).

        Keeps each instrument's last bars and the data problems still holding it out,
        exactly as the same sessions arriving as events would, but publishes nothing.
        Call it before the run's first event, with each calendar's sessions in order
        and all of them before that event.

        Args:
            histories: Cached history of each instrument, from at least the first of
                ``sessions``. Bars outside ``sessions`` are ignored.
            sessions: For each calendar the instruments follow, the sessions to learn.
        """
        for history in histories:
            instrument = history.instrument
            calendar_sessions = sessions.get(instrument.calendar)
            if calendar_sessions is None:
                raise UniverseError(
                    f"no warm-up sessions given for calendar {instrument.calendar} of {instrument}"
                )
            bars = {bar.timestamp: bar for bar in history.bars}
            issues: dict[date, list[DataIssue]] = defaultdict(list)
            for issue in history.issues:
                if issue.session_day is not None:
                    issues[issue.session_day].append(issue)
            for session in calendar_sessions:
                bar = bars.get(session.closes_at)
                if bar is not None:
                    self._add_bar(bar)
                for issue in issues.get(session.day, ()):
                    self._note_issue(issue)
                self._count_down(instrument)

    # --- what the stage is told ------------------------------------------------------

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        self._add_bar(envelope.event.bar)

    def _add_bar(self, bar: Bar) -> None:
        _require_daily(bar.timeframe, f"a bar of {bar.instrument}")
        window = self._bars.setdefault(bar.instrument, deque(maxlen=self._rules.liquidity_sessions))
        if window and bar.timestamp <= window[-1].timestamp:
            raise UniverseError(
                f"bars of {bar.instrument} arrived out of order: {bar.timestamp.isoformat()} "
                f"after {window[-1].timestamp.isoformat()}"
            )
        window.append(bar)

    def _on_issue(self, envelope: Envelope[DataQualityEvent]) -> None:
        self._note_issue(envelope.event.issue)

    def _note_issue(self, issue: DataIssue) -> None:
        if issue.kind in DISQUALIFYING_ISSUES and issue.session_day is not None:
            self._quarantine[issue.instrument] = _Quarantine(issue, self._rules.quality_sessions)

    def _on_ready(self, envelope: Envelope[DataReadyEvent]) -> None:
        ready = envelope.event
        _require_daily(ready.timeframe, "a DataReadyEvent")
        eligible: list[UniverseMember] = []
        excluded: list[Exclusion] = []
        expected = [(i, True) for i in ready.delivered] + [(i, False) for i in ready.missing]
        for instrument, has_bar in expected:
            verdict = self._judge(instrument, has_bar, ready.as_of)
            if isinstance(verdict, UniverseMember):
                eligible.append(verdict)
            else:
                excluded.append(verdict)
        for instrument, _ in expected:
            self._count_down(instrument)
        self._bus.publish(UniverseEvent(ready.as_of, tuple(eligible), tuple(excluded)))

    # --- the rules ---------------------------------------------------------------------

    def _judge(
        self, instrument: Instrument, has_bar: bool, as_of: datetime
    ) -> UniverseMember | Exclusion:
        def exclude(reason: ExclusionReason, detail: str) -> Exclusion:
            return Exclusion(instrument, reason, detail)

        outside = self._outside_profile(instrument)
        if outside is not None:
            return exclude(ExclusionReason.NOT_IN_PROFILE, outside)

        if not has_bar:
            return exclude(ExclusionReason.NO_BAR, f"no bar for {as_of.isoformat()}")

        quarantine = self._quarantine.get(instrument)
        if quarantine is not None:
            issue = quarantine.issue
            day = issue.session_day.isoformat() if issue.session_day else "an unknown day"
            return exclude(
                ExclusionReason.DATA_ISSUE,
                f"{issue.kind} on {day}: {issue.detail}; left out for "
                f"{quarantine.cycles_left} cycle(s) including this one",
            )

        window = self._bars.get(instrument)
        if not window or window[-1].timestamp != as_of:
            raise UniverseError(
                f"{instrument} is listed as delivered at {as_of.isoformat()}, "
                "but its bar for that time never arrived"
            )

        needed = self._rules.liquidity_sessions
        if len(window) < needed:
            return exclude(
                ExclusionReason.INSUFFICIENT_HISTORY,
                f"{len(window)} of the {needed} bars the liquidity average needs",
            )

        close = window[-1].close
        if close < self._min_price:
            return exclude(
                ExclusionReason.PRICE_TOO_LOW,
                f"last close {close:.2f} is below the minimum {self._rules.min_price}",
            )

        dollar_volume = sum(bar.close * bar.volume for bar in window) / len(window)
        if dollar_volume < self._min_dollar_volume:
            return exclude(
                ExclusionReason.ILLIQUID,
                f"average dollar volume {dollar_volume:,.0f} over {needed} bars is below "
                f"the minimum {self._rules.min_average_dollar_volume}",
            )

        return UniverseMember(instrument, close, dollar_volume)

    def _outside_profile(self, instrument: Instrument) -> str | None:
        """Why ``instrument`` is outside the profile, or ``None`` if it is inside."""
        profile = self._profile
        if instrument.calendar not in profile.calendars:
            return f"calendar {instrument.calendar} is not one of profile {profile.name}'s"
        if instrument.currency is not self._rules.currency:
            return (
                f"quoted in {instrument.currency}; profile {profile.name} has universe "
                f"thresholds in {self._rules.currency} only"
            )
        if instrument.asset_class not in self._rules.asset_classes:
            return f"asset class {instrument.asset_class} is not allowed in profile {profile.name}"
        return None

    def _count_down(self, instrument: Instrument) -> None:
        quarantine = self._quarantine.get(instrument)
        if quarantine is None:
            return
        quarantine.cycles_left -= 1
        if quarantine.cycles_left == 0:
            del self._quarantine[instrument]


def _require_daily(timeframe: Timeframe, what: str) -> None:
    if timeframe is not Timeframe.D1:
        raise UniverseError(
            f"the universe stage handles daily data only (Phase 1), got {what} at {timeframe}"
        )

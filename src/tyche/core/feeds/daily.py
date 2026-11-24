"""DailyFeed: each session's bars after its close, for paper and live (ADR-0043).

A paper or live run starts after a close. It is handed the cached histories (fetched
through the read-through cache, which waits ``after_close`` before a session's bars
count as final) and the first session it has not yet seen. The feed then publishes
every session from that one through the latest final one, oldest first, **exactly as
the historical replay would**: it is the replay, re-stamped with the wall clock.

Only one thing differs. A session's ``DataReadyEvent`` starts a decision cycle, and a
decision may trade only until ``before_next_open`` before the next session's open.
When the feed reaches a session's ``DataReadyEvent``, it reads the clock:

* still in time, with a bar for every candidate: the ``DataReadyEvent`` is published
  and the cycle runs;
* too late (always the case for a missed session, whose next session has already
  traded): a ``CycleSkippedEvent`` with reason ``STALE`` is published instead;
* in time, but a candidate has no bar: a ``CycleSkippedEvent`` with reason
  ``INCOMPLETE``. Two hours after the close a missing bar is a data failure, and
  deciding without it could act on half a picture.

A skipped cycle sends no order, but its session's bars and closes are still published,
so the signals windows, Tyche's view of the account, the daily loss limit and the
drawdown kill see every close, as they would have if the machine had not slept.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime

from tyche.core.domain import BarHistory, DailyCycleRules, Session
from tyche.core.events import CycleSkippedEvent, DataReadyEvent, SkipReason
from tyche.core.ports import Calendar, Clock, FeedInput
from tyche.core.sim import SOURCE_REPLAY, HistoricalReplay

SOURCE = "daily_feed"


class DailyFeed:
    """Implements the ``Feed`` port for paper and live, one daily run at a time.

    Args:
        histories: One audited history per candidate, in publishing order, covering at
            least the sessions to publish. The market profile's candidates, exactly
            (ADR-0024).
        calendar: The calendar every candidate follows.
        clock: The wall clock. Read once here, to decide which sessions are final,
            and again as each input is published, to stamp it and to judge freshness.
        rules: The market profile's ``daily_cycle``.
        first: The first session day not yet seen: the day after the last close of the
            previous run's checkpoint, or the latest session for a first run.

    Raises:
        ValueError: A history follows another calendar, or repeats an instrument.

    One calendar for now: ``CA+US`` (Phase 4) needs sessions of two calendars merged,
    each with its own next open.
    """

    def __init__(
        self,
        histories: Sequence[BarHistory],
        calendar: Calendar,
        clock: Clock,
        rules: DailyCycleRules,
        first: date,
    ) -> None:
        others = sorted(
            {str(h.instrument) for h in histories if h.instrument.calendar != calendar.mic}
        )
        if others:
            raise ValueError(
                f"the daily feed follows one calendar, {calendar.mic}; "
                f"{', '.join(others)} follow another"
            )
        self._clock = clock
        now = clock.now()
        # New York's session day is never after the UTC date, so this range holds every
        # session that can have closed.
        candidates = calendar.sessions_between(first, now.date()) if first <= now.date() else ()
        self._sessions = tuple(s for s in candidates if rules.ready_at(s) <= now)
        # Looked up now, so a calendar loaded too short fails before the run starts.
        self._trade_until = {
            session.closes_at: rules.trade_until(calendar.next_session(session.day))
            for session in self._sessions
        }
        self._replay = (
            HistoricalReplay(histories, {calendar.mic: calendar}, first, self._sessions[-1].day)
            if self._sessions
            else None
        )
        self._traded: Session | None = None
        self._skipped: list[CycleSkippedEvent] = []

    @property
    def sessions(self) -> tuple[Session, ...]:
        """The sessions this run publishes, oldest first. Empty if none is final yet."""
        return self._sessions

    @property
    def starts_at(self) -> datetime | None:
        """The first session's open: warm-up must stop before it (ADR-0021)."""
        return self._sessions[0].opens_at if self._sessions else None

    @property
    def traded(self) -> Session | None:
        """The session whose decision cycle ran, once published."""
        return self._traded

    @property
    def skipped(self) -> tuple[CycleSkippedEvent, ...]:
        """The cycles skipped so far, oldest first."""
        return tuple(self._skipped)

    def inputs(self) -> Iterator[FeedInput]:
        if self._replay is None:
            return
        by_close = {session.closes_at: session for session in self._sessions}
        for item in self._replay.inputs():
            at = self._clock.now()
            source = SOURCE if item.source == SOURCE_REPLAY else item.source
            event = item.event
            if not isinstance(event, DataReadyEvent):
                yield FeedInput(at, event, source)
                continue
            trade_until = self._trade_until[event.as_of]
            if at >= trade_until:
                reason: SkipReason | None = SkipReason.STALE
            elif event.missing:
                reason = SkipReason.INCOMPLETE
            else:
                reason = None
            if reason is None:
                self._traded = by_close[event.as_of]
                yield FeedInput(at, event, source, item.cycle_id)
                continue
            skipped = CycleSkippedEvent(
                timeframe=event.timeframe,
                as_of=event.as_of,
                reason=reason,
                trade_until=trade_until,
                delivered=event.delivered,
                missing=event.missing,
            )
            self._skipped.append(skipped)
            yield FeedInput(at, skipped, source)

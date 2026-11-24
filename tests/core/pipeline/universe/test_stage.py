"""The universe stage: every expected instrument is eligible or excluded, with a reason."""

from dataclasses import replace
from datetime import date

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of, session
from tests.support.profiles import US_PROFILE, US_RULES, usd
from tests.support.recording import Recorder, TickingClock
from tyche.core.domain import (
    AssetClass,
    Bar,
    BarHistory,
    Currency,
    DataIssue,
    DataIssueKind,
    ExclusionReason,
    Instrument,
    MarketProfile,
    Timeframe,
    UniverseMember,
)
from tyche.core.events import (
    BarEvent,
    CycleSkippedEvent,
    DataQualityEvent,
    DataReadyEvent,
    EventBus,
    HandlerError,
    SkipReason,
    UniverseEvent,
)
from tyche.core.pipeline.universe import UniverseError, UniverseStage

# Small numbers keep the arithmetic visible: three bars for the average, two cycles out
# after a data issue, at least $5 a share and $1M a day.
RULES = replace(
    US_RULES,
    min_average_dollar_volume=usd("1000000"),
    liquidity_sessions=3,
    quality_sessions=2,
)
PROFILE = replace(US_PROFILE, universe=RULES)

D1, D2, D3, D4, D5, D6 = JANUARY_2024[:6]


class Harness:
    """Publishes one session's inputs in the replay's order and collects the result."""

    def __init__(self, profile: MarketProfile = PROFILE) -> None:
        self.bus = EventBus(TickingClock().now)
        self.stage = UniverseStage(self.bus, profile)
        self.recorder = Recorder(self.bus)

    def session(
        self,
        day: date,
        bars: list[Bar],
        *,
        missing: tuple[Instrument, ...] = (),
        issues: tuple[DataIssue, ...] = (),
        skip: bool = False,
    ) -> UniverseEvent:
        for b in bars:
            self.bus.publish(BarEvent(b), source="replay")
        for issue in issues:
            self.bus.publish(DataQualityEvent(issue), source="replay")
        delivered = tuple(b.instrument for b in bars)
        if skip:
            stale = CycleSkippedEvent(
                Timeframe.D1, close_of(day), SkipReason.STALE, close_of(day), delivered, missing
            )
            self.bus.publish(stale, source="daily_feed")
        else:
            ready = DataReadyEvent(Timeframe.D1, close_of(day), delivered, missing)
            self.bus.publish(ready, source="replay", cycle_id=f"XNYS:{day}:1d")
        self.bus.drain()
        return self.latest

    @property
    def latest(self) -> UniverseEvent:
        found = [e for e in self.recorder.events if isinstance(e, UniverseEvent)]
        return found[-1]

    def warm_up(self, *instruments: Instrument, close: float = 100.0) -> UniverseEvent:
        """Three clean sessions, D1 to D3, enough for every rule to be checked."""
        for day in (D1, D2, D3):
            self.session(day, [bar(day, close, instrument=i) for i in instruments])
        return self.latest


def reasons(event: UniverseEvent) -> dict[str, ExclusionReason]:
    return {e.instrument.symbol: e.reason for e in event.excluded}


def eligible(event: UniverseEvent) -> list[str]:
    return [m.instrument.symbol for m in event.eligible]


def issue(kind: DataIssueKind, day: date | None, instrument: Instrument = SPY) -> DataIssue:
    return DataIssue(kind, instrument, day, "something was wrong")


class TestEligible:
    def test_an_instrument_passing_every_rule_is_eligible_with_its_measurements(self) -> None:
        h = Harness()

        event = h.warm_up(SPY)

        # bar(): close 100, volume 1,000,000, so 100M dollars a day.
        assert event.eligible == (UniverseMember(SPY, 100.0, 100_000_000.0),)
        assert event.excluded == ()
        assert event.as_of == close_of(D3)

    def test_the_average_covers_only_the_last_liquidity_sessions_bars(self) -> None:
        h = Harness()
        for day, close in zip((D1, D2, D3, D4), (10.0, 20.0, 30.0, 40.0), strict=True):
            event = h.session(day, [bar(day, close)])

        # D2 to D4: (20 + 30 + 40) / 3 million dollars.
        assert event.eligible[0].average_dollar_volume == pytest.approx(30_000_000.0)
        assert event.eligible[0].last_close == 40.0

    def test_one_event_per_cycle_in_the_feeds_order_with_the_cycle_inherited(self) -> None:
        h = Harness()
        h.warm_up(QQQ, SPY)

        universes = [e for e in h.recorder if isinstance(e.event, UniverseEvent)]
        assert [e.cycle_id for e in universes] == [f"XNYS:{d}:1d" for d in (D1, D2, D3)]
        assert {e.source for e in universes} == {"universe"}
        assert eligible(h.latest) == ["QQQ", "SPY"]

    def test_each_universe_event_is_caused_by_its_data_ready_event(self) -> None:
        h = Harness()
        h.warm_up(SPY)

        by_seq = {e.seq: e for e in h.recorder}
        for envelope in h.recorder:
            if isinstance(envelope.event, UniverseEvent):
                assert envelope.caused_by is not None
                assert isinstance(by_seq[envelope.caused_by].event, DataReadyEvent)


class TestNotInProfile:
    def test_an_instrument_on_another_calendar(self) -> None:
        xiu = Instrument("XIU", "XTSE", Currency.USD, "XTSE", AssetClass.ETF)
        h = Harness()

        event = h.session(D1, [bar(D1, instrument=xiu)])

        assert reasons(event) == {"XIU": ExclusionReason.NOT_IN_PROFILE}
        assert "calendar XTSE" in event.excluded[0].detail

    def test_an_instrument_in_another_currency(self) -> None:
        cad = Instrument("RY", "XNYS", Currency.CAD, "XNYS", AssetClass.STOCK)
        h = Harness()

        event = h.session(D1, [bar(D1, instrument=cad)])

        assert reasons(event) == {"RY": ExclusionReason.NOT_IN_PROFILE}
        assert "quoted in CAD" in event.excluded[0].detail

    def test_an_asset_class_the_profile_does_not_allow(self) -> None:
        h = Harness(
            replace(
                PROFILE, universe=replace(RULES, asset_classes=(AssetClass.STOCK,), instruments=())
            )
        )

        event = h.warm_up(SPY)

        assert reasons(event) == {"SPY": ExclusionReason.NOT_IN_PROFILE}
        assert "asset class etf" in event.excluded[0].detail

    def test_comes_before_every_other_rule(self) -> None:
        xiu = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)
        h = Harness()

        event = h.session(D1, [], missing=(xiu,))

        assert reasons(event) == {"XIU": ExclusionReason.NOT_IN_PROFILE}


class TestNoBar:
    def test_a_missing_instrument_is_excluded_for_that_cycle(self) -> None:
        h = Harness()
        h.warm_up(SPY, QQQ)

        event = h.session(D4, [bar(D4)], missing=(QQQ,))

        assert eligible(event) == ["SPY"]
        assert reasons(event) == {"QQQ": ExclusionReason.NO_BAR}

    def test_exclusions_keep_the_feeds_order_delivered_before_missing(self) -> None:
        h = Harness()

        event = h.session(D1, [bar(D1)], missing=(QQQ,))

        assert [e.instrument for e in event.excluded] == [SPY, QQQ]


class TestDataQuality:
    @pytest.mark.parametrize(
        "kind",
        [
            DataIssueKind.MISSING_SESSION,
            DataIssueKind.CONFLICT,
            DataIssueKind.INVALID_BAR,
            DataIssueKind.SUSPECT_MOVE,
        ],
    )
    def test_a_disqualifying_issue_keeps_an_instrument_out_for_quality_sessions_cycles(
        self, kind: DataIssueKind
    ) -> None:
        h = Harness()
        h.warm_up(SPY)

        on_d4 = h.session(D4, [bar(D4)], issues=(issue(kind, D4),))
        on_d5 = h.session(D5, [bar(D5)])
        on_d6 = h.session(D6, [bar(D6)])

        assert reasons(on_d4) == {"SPY": ExclusionReason.DATA_ISSUE}
        assert reasons(on_d5) == {"SPY": ExclusionReason.DATA_ISSUE}
        assert eligible(on_d6) == ["SPY"]
        assert "2 cycle(s) including this one" in on_d4.excluded[0].detail
        assert "1 cycle(s) including this one" in on_d5.excluded[0].detail
        assert f"{kind} on {D4.isoformat()}" in on_d4.excluded[0].detail

    def test_a_skipped_cycle_counts_as_a_session_out(self) -> None:
        # ADR-0043: a catch-up publishes missed sessions with their cycles skipped. The
        # count goes on, so the stage ends as it would have if every cycle had run.
        h = Harness()
        h.warm_up(SPY)

        h.session(D4, [bar(D4)], issues=(issue(DataIssueKind.SUSPECT_MOVE, D4),), skip=True)
        h.session(D5, [bar(D5)], skip=True)
        on_d6 = h.session(D6, [bar(D6)])

        assert eligible(on_d6) == ["SPY"]

    def test_a_skipped_cycle_publishes_no_universe(self) -> None:
        h = Harness()
        h.warm_up(SPY)
        before = len(h.recorder.events)

        h.session(D4, [bar(D4)], skip=True)

        assert not [e for e in h.recorder.events[before:] if isinstance(e, UniverseEvent)]

    def test_a_duplicate_bar_is_not_held_against_an_instrument(self) -> None:
        h = Harness()
        h.warm_up(SPY)

        event = h.session(D4, [bar(D4)], issues=(issue(DataIssueKind.DUPLICATE, D4),))

        assert eligible(event) == ["SPY"]

    def test_an_issue_without_a_session_day_is_not_held_against_an_instrument(self) -> None:
        h = Harness()
        h.warm_up(SPY)

        event = h.session(D4, [bar(D4)], issues=(issue(DataIssueKind.OFF_SESSION, None),))

        assert eligible(event) == ["SPY"]

    def test_a_new_issue_restarts_the_count(self) -> None:
        h = Harness()
        h.warm_up(SPY)

        h.session(D4, [bar(D4)], issues=(issue(DataIssueKind.SUSPECT_MOVE, D4),))
        h.session(D5, [bar(D5)], issues=(issue(DataIssueKind.SUSPECT_MOVE, D5),))
        on_d6 = h.session(D6, [bar(D6)])

        assert reasons(on_d6) == {"SPY": ExclusionReason.DATA_ISSUE}

    def test_a_missing_session_is_reported_as_no_bar_first_then_as_a_data_issue(self) -> None:
        h = Harness()
        h.warm_up(SPY)
        missing = issue(DataIssueKind.MISSING_SESSION, D4)

        on_d4 = h.session(D4, [], missing=(SPY,), issues=(missing,))
        on_d5 = h.session(D5, [bar(D5)])
        on_d6 = h.session(D6, [bar(D6)])

        assert reasons(on_d4) == {"SPY": ExclusionReason.NO_BAR}
        assert reasons(on_d5) == {"SPY": ExclusionReason.DATA_ISSUE}
        assert eligible(on_d6) == ["SPY"]

    def test_an_issue_about_one_instrument_does_not_affect_another(self) -> None:
        h = Harness()
        h.warm_up(SPY, QQQ)

        event = h.session(
            D4,
            [bar(D4), bar(D4, instrument=QQQ)],
            issues=(issue(DataIssueKind.CONFLICT, D4, QQQ),),
        )

        assert eligible(event) == ["SPY"]
        assert reasons(event) == {"QQQ": ExclusionReason.DATA_ISSUE}


class TestHistory:
    def test_fewer_bars_than_the_average_needs(self) -> None:
        h = Harness()

        on_d1 = h.session(D1, [bar(D1)])
        on_d2 = h.session(D2, [bar(D2)])
        on_d3 = h.session(D3, [bar(D3)])

        assert reasons(on_d1) == {"SPY": ExclusionReason.INSUFFICIENT_HISTORY}
        assert on_d1.excluded[0].detail == "1 of the 3 bars the liquidity average needs"
        assert reasons(on_d2) == {"SPY": ExclusionReason.INSUFFICIENT_HISTORY}
        assert eligible(on_d3) == ["SPY"]


class TestPrice:
    def test_a_last_close_below_the_minimum(self) -> None:
        h = Harness()

        event = h.warm_up(SPY, close=4.99)

        assert reasons(event) == {"SPY": ExclusionReason.PRICE_TOO_LOW}
        assert event.excluded[0].detail == "last close 4.99 is below the minimum 5.00 USD"

    def test_exactly_the_minimum_is_allowed(self) -> None:
        h = Harness(replace(PROFILE, universe=replace(RULES, min_average_dollar_volume=usd("0"))))

        assert eligible(h.warm_up(SPY, close=5.0)) == ["SPY"]


class TestLiquidity:
    def test_an_average_dollar_volume_below_the_minimum(self) -> None:
        h = Harness(replace(PROFILE, universe=replace(RULES, min_average_dollar_volume=usd("2e8"))))

        event = h.warm_up(SPY)

        assert reasons(event) == {"SPY": ExclusionReason.ILLIQUID}
        assert "average dollar volume 100,000,000 over 3 bars" in event.excluded[0].detail

    def test_exactly_the_minimum_is_allowed(self) -> None:
        h = Harness(replace(PROFILE, universe=replace(RULES, min_average_dollar_volume=usd("1e8"))))

        assert eligible(h.warm_up(SPY)) == ["SPY"]


class TestFailsClosed:
    def test_an_intraday_bar_halts_the_run(self) -> None:
        h = Harness()
        h.bus.publish(BarEvent(bar(D1, timeframe=Timeframe.H1)), source="replay")

        with pytest.raises(HandlerError) as raised:
            h.bus.drain()
        assert isinstance(raised.value.__cause__, UniverseError)
        assert "daily data only" in str(raised.value.__cause__)

    def test_an_intraday_data_ready_event_halts_the_run(self) -> None:
        h = Harness()
        h.bus.publish(DataReadyEvent(Timeframe.H1, close_of(D1), ()), source="replay")

        with pytest.raises(HandlerError) as raised:
            h.bus.drain()
        assert isinstance(raised.value.__cause__, UniverseError)

    def test_a_delivered_instrument_whose_bar_never_arrived_halts_the_run(self) -> None:
        h = Harness()
        h.bus.publish(DataReadyEvent(Timeframe.D1, close_of(D1), (SPY,)), source="replay")

        with pytest.raises(HandlerError) as raised:
            h.bus.drain()
        assert "never arrived" in str(raised.value.__cause__)

    def test_bars_out_of_order_halt_the_run(self) -> None:
        h = Harness()
        h.bus.publish(BarEvent(bar(D2)), source="replay")
        h.bus.publish(BarEvent(bar(D1)), source="replay")

        with pytest.raises(HandlerError) as raised:
            h.bus.drain()
        assert "out of order" in str(raised.value.__cause__)


class TestWarmUp:
    """Warming up on sessions gives the same judgement as playing them as events."""

    def played(self, sessions: list[tuple[date, list[Bar], tuple[DataIssue, ...]]]) -> Harness:
        h = Harness()
        for day, bars, issues in sessions:
            h.session(
                day,
                bars,
                missing=(QQQ,) if QQQ not in {b.instrument for b in bars} else (),
                issues=issues,
            )
        return h

    def warmed(self, sessions: list[tuple[date, list[Bar], tuple[DataIssue, ...]]]) -> Harness:
        h = Harness()
        histories = [
            BarHistory(
                instrument,
                tuple(b for _, bars, _ in sessions for b in bars if b.instrument == instrument),
                issues=tuple(
                    i for _, _, issues in sessions for i in issues if i.instrument == instrument
                ),
            )
            for instrument in (QQQ, SPY)
        ]
        h.stage.warm_up(histories, {"XNYS": [session(day) for day, _, _ in sessions]})
        return h

    def history(self) -> list[tuple[date, list[Bar], tuple[DataIssue, ...]]]:
        # QQQ misses D3 and its data on D4 is suspect; SPY trades every day.
        days: list[tuple[date, list[Bar], tuple[DataIssue, ...]]] = []
        for day, close in zip((D1, D2, D3, D4), (10.0, 20.0, 30.0, 40.0), strict=True):
            bars = [bar(day, close)]
            if day != D3:
                bars.append(bar(day, close * 2, instrument=QQQ))
            found = (issue(DataIssueKind.SUSPECT_MOVE, D4, QQQ),) if day == D4 else ()
            days.append((day, bars, found))
        return days

    def test_the_next_decision_matches_one_made_after_playing_every_session(self) -> None:
        today = [bar(D5, 50.0), bar(D5, 100.0, instrument=QQQ)]
        played = self.played(self.history())
        warmed = self.warmed(self.history())

        expected = played.session(D5, today)
        actual = warmed.session(D5, today)

        assert actual.eligible == expected.eligible
        assert actual.excluded == expected.excluded
        assert eligible(actual) == ["SPY"]
        assert reasons(actual) == {"QQQ": ExclusionReason.DATA_ISSUE}

    def test_publishes_nothing(self) -> None:
        warmed = self.warmed(self.history())

        assert warmed.recorder.events == []

    def test_needs_sessions_for_every_calendar(self) -> None:
        h = Harness()

        with pytest.raises(UniverseError, match="no warm-up sessions given for calendar XNYS"):
            h.stage.warm_up([BarHistory(SPY, ())], {})

    def test_history_needed_covers_the_average_and_the_quarantine(self) -> None:
        assert UniverseStage(EventBus(TickingClock().now), PROFILE).history_needed == 3
        longer = replace(PROFILE, universe=replace(RULES, quality_sessions=7))
        assert UniverseStage(EventBus(TickingClock().now), longer).history_needed == 7

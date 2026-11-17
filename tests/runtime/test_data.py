"""The fetch wiring: instruments from symbols, and a fetch that never stops at one failure."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.adapters.data.test_yfinance_source import FakeFetch, row
from tests.support.market import JANUARY_2024
from tyche.adapters.data import YFinanceSource
from tyche.adapters.data.yfinance_source import UnknownSymbolError
from tyche.config import TycheConfig, init_workspace, load_config
from tyche.core.domain import AssetClass, Currency, Instrument, MarketProfile
from tyche.core.ports import Calendar
from tyche.core.sim import SimClock
from tyche.runtime.data import (
    CALENDAR_START,
    FetchRequestError,
    fetch_daily_histories,
    instrument_for,
)

US = MarketProfile("US", (Currency.USD,), ("XNYS",))
CA = MarketProfile("CA", (Currency.CAD,), ("XTSE",))
AFTER_JANUARY_16 = SimClock(datetime(2024, 1, 17, 12, 0, tzinfo=UTC))


@pytest.fixture
def config(tmp_path: Path) -> TycheConfig:
    home = tmp_path / "home"
    home.mkdir()
    return load_config(init_workspace(home / "ws", user_home=home))


class TestInstrumentFor:
    def test_builds_an_instrument_from_the_exchange(self) -> None:
        assert instrument_for("spy", "ARCX", AssetClass.ETF, US) == Instrument(
            "SPY", "ARCX", Currency.USD, "XNYS", AssetClass.ETF
        )

    def test_an_unknown_exchange_lists_the_known_ones(self) -> None:
        with pytest.raises(
            FetchRequestError, match="unknown exchange 'XTSE'; known exchanges: ARCX"
        ):
            instrument_for("XIU", "XTSE", AssetClass.ETF, US)

    def test_an_exchange_outside_the_profile_is_refused(self) -> None:
        with pytest.raises(FetchRequestError, match=r"NYSE Arca .* not part of market profile CA"):
            instrument_for("SPY", "ARCX", AssetClass.ETF, CA)

    def test_a_malformed_symbol_is_refused(self) -> None:
        with pytest.raises(FetchRequestError, match="invalid symbol"):
            instrument_for("S P Y", "ARCX", AssetClass.ETF, US)


class TestFetch:
    def spy(self) -> Instrument:
        return instrument_for("SPY", "ARCX", AssetClass.ETF, US)

    def source(
        self, fetch: FakeFetch, calendars: dict[str, Calendar] | None = None
    ) -> YFinanceSource:
        from tyche.adapters.calendars import ExchangeCalendarsCalendar

        nyse = ExchangeCalendarsCalendar("XNYS", first=CALENDAR_START, last=date(2024, 12, 31))
        return YFinanceSource(calendars or {"XNYS": nyse}, fetch=fetch)

    def test_fetches_audits_and_caches_in_the_workspace(self, config: TycheConfig) -> None:
        fetch = FakeFetch([row(day) for day in JANUARY_2024])

        [outcome] = fetch_daily_histories(
            config,
            [self.spy()],
            date(2024, 1, 2),
            date(2024, 1, 16),
            source=self.source(fetch),
            clock=AFTER_JANUARY_16,
        )

        assert outcome.error is None
        assert outcome.history is not None
        assert len(outcome.history.bars) == len(JANUARY_2024)
        assert not outcome.history.has_issues
        cached = config.workspace.data_dir / "bars" / "yfinance" / "1d" / "ARCX" / "SPY.parquet"
        assert cached.is_file()

    def test_one_failure_does_not_stop_the_others(self, config: TycheConfig) -> None:
        qqq = instrument_for("QQQ", "XNAS", AssetClass.ETF, US)
        fetch = FakeFetch(
            UnknownSymbolError("no timezone found"), [row(day) for day in JANUARY_2024]
        )

        outcomes = fetch_daily_histories(
            config,
            [self.spy(), qqq],
            date(2024, 1, 2),
            date(2024, 1, 16),
            source=self.source(fetch),
            clock=AFTER_JANUARY_16,
        )

        assert [o.instrument.symbol for o in outcomes] == ["SPY", "QQQ"]
        assert outcomes[0].error is not None
        assert "does not know the symbol 'SPY'" in outcomes[0].error
        assert outcomes[1].history is not None

    def test_the_last_date_defaults_to_today_on_the_clock(self, config: TycheConfig) -> None:
        fetch = FakeFetch([row(day) for day in JANUARY_2024])

        fetch_daily_histories(
            config,
            [self.spy()],
            date(2024, 1, 2),
            source=self.source(fetch),
            clock=AFTER_JANUARY_16,
        )

        assert fetch.calls == [("SPY", date(2024, 1, 2), date(2024, 1, 17))]

    def test_cannot_start_before_the_calendars_do(self, config: TycheConfig) -> None:
        with pytest.raises(
            FetchRequestError, match="earliest date Tyche can fetch from is 1990-01-01"
        ):
            fetch_daily_histories(config, [self.spy()], date(1989, 12, 29), date(1990, 1, 5))

    def test_an_empty_range_is_refused(self, config: TycheConfig) -> None:
        with pytest.raises(FetchRequestError, match="empty date range"):
            fetch_daily_histories(config, [self.spy()], date(2024, 1, 5), date(2024, 1, 2))

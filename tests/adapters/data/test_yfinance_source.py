"""The yfinance source: Yahoo's rows become bars at session closes, with retries.

No test here touches the network except the one marked ``network``, which is opt-in.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yfinance
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError
from requests.exceptions import HTTPError as RequestsHTTPError

from tests.support.market import QQQ, SPY
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data.yfinance_source import (
    NoDataError,
    TemporaryFailureError,
    UnknownSymbolError,
    YahooRow,
    YFinanceSource,
    convert_rows,
    rows_from_frame,
    yahoo_ticker,
    yfinance_fetcher,
)
from tyche.core.domain import (
    AssetClass,
    Currency,
    DataIssueKind,
    DistributionKind,
    Instrument,
    PriceAdjustment,
)
from tyche.core.ports import Calendar, DataError


@pytest.fixture(scope="module")
def nyse() -> Calendar:
    return ExchangeCalendarsCalendar("XNYS", first=date(2024, 1, 1), last=date(2024, 12, 31))


def row(day: date, close: float = 100.0, **actions: float) -> YahooRow:
    return YahooRow(day, close * 0.99, close * 1.02, close * 0.98, close, 1_000_000.0, **actions)


class TestTicker:
    def test_us_symbols_are_used_as_they_are(self) -> None:
        assert yahoo_ticker(SPY) == "SPY"

    def test_share_classes_use_a_hyphen(self) -> None:
        brk = Instrument("BRK.B", "XNYS", Currency.USD, "XNYS", AssetClass.STOCK)

        assert yahoo_ticker(brk) == "BRK-B"

    def test_other_markets_are_not_supported_yet(self) -> None:
        toronto = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)

        with pytest.raises(DataError, match="does not support XTSE listings yet"):
            yahoo_ticker(toronto)


class TestConvertRows:
    def test_bars_are_stamped_at_the_session_close(self, nyse: Calendar) -> None:
        days = [date(2024, 1, 2), date(2024, 7, 1), date(2024, 7, 3)]  # winter, summer, half day

        data = convert_rows(SPY, [row(day) for day in days], nyse)

        assert [b.timestamp for b in data.bars] == [
            datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
            datetime(2024, 7, 1, 20, 0, tzinfo=UTC),
            datetime(2024, 7, 3, 17, 0, tzinfo=UTC),
        ]
        assert all(b.adjustment is PriceAdjustment.SPLITS for b in data.bars)

    def test_a_row_for_a_closed_day_becomes_an_issue(self, nyse: Calendar) -> None:
        data = convert_rows(SPY, [row(date(2024, 7, 4))], nyse)

        assert data.bars == ()
        assert [(i.kind, i.session_day) for i in data.issues] == [
            (DataIssueKind.OFF_SESSION, date(2024, 7, 4))
        ]

    def test_impossible_prices_become_an_issue(self, nyse: Calendar) -> None:
        broken = YahooRow(date(2024, 1, 2), 100.0, 99.0, 98.0, 100.0, 1.0)  # high below close

        data = convert_rows(SPY, [broken], nyse)

        assert data.bars == ()
        assert data.issues[0].kind is DataIssueKind.INVALID_BAR
        assert "high 99.0 is below another price" in data.issues[0].detail

    def test_dividends_and_capital_gains_are_exact_cash_events(self, nyse: Calendar) -> None:
        data = convert_rows(
            SPY,
            [row(date(2024, 3, 15), dividend=1.595), row(date(2024, 12, 20), capital_gain=0.75)],
            nyse,
        )

        assert [(d.ex_date, d.amount_per_share.amount, d.kind) for d in data.distributions] == [
            (date(2024, 3, 15), Decimal("1.595"), DistributionKind.DIVIDEND),
            (date(2024, 12, 20), Decimal("0.75"), DistributionKind.CAPITAL_GAIN),
        ]
        assert all(d.amount_per_share.currency is Currency.USD for d in data.distributions)

    def test_splits_keep_whole_ratios_whole(self, nyse: Calendar) -> None:
        data = convert_rows(
            QQQ, [row(date(2024, 6, 10), split=10.0), row(date(2024, 6, 11), split=0.25)], nyse
        )

        assert [s.ratio for s in data.splits] == [Decimal(10), Decimal("0.25")]
        assert str(data.splits[0]) == "QQQ@XNAS split 10-for-1 ex 2024-06-10"

    def test_zero_and_missing_actions_are_ignored(self, nyse: Calendar) -> None:
        data = convert_rows(SPY, [row(date(2024, 1, 2), dividend=0.0, split=float("nan"))], nyse)

        assert data.distributions == ()
        assert data.splits == ()


class TestRowsFromFrame:
    def frame(self, *, with_capital_gains: bool) -> pd.DataFrame:
        index = pd.DatetimeIndex(["2024-03-14", "2024-03-15"]).tz_localize("America/New_York")
        columns: dict[str, list[float]] = {
            "Open": [516.97, 510.21],
            "High": [517.13, 511.70],
            "Low": [511.82, 508.12],
            "Close": [514.95, 509.83],
            "Adj Close": [498.63, 495.21],
            "Volume": [110171800.0, 107646300.0],
            "Dividends": [0.0, 1.595],
            "Stock Splits": [0.0, 0.0],
        }
        if with_capital_gains:
            columns["Capital Gains"] = [0.0, 0.0]
        return pd.DataFrame(columns, index=index)

    def test_reads_the_columns_yfinance_returns(self) -> None:
        rows = rows_from_frame(self.frame(with_capital_gains=True))

        assert rows == [
            YahooRow(date(2024, 3, 14), 516.97, 517.13, 511.82, 514.95, 110171800.0),
            YahooRow(
                date(2024, 3, 15), 510.21, 511.70, 508.12, 509.83, 107646300.0, dividend=1.595
            ),
        ]

    def test_uses_the_split_adjusted_close_not_adj_close(self) -> None:
        assert rows_from_frame(self.frame(with_capital_gains=False))[0].close == 514.95

    def test_a_missing_capital_gains_column_counts_as_zero(self) -> None:
        assert all(
            r.capital_gain == 0.0 for r in rows_from_frame(self.frame(with_capital_gains=False))
        )


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeFetch:
    """Plays back a script of answers: a list of rows, or an exception to raise."""

    def __init__(self, *script: list[YahooRow] | Exception) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, ticker: str, start: date, end: date) -> list[YahooRow]:
        self.calls.append((ticker, start, end))
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class TestFetchDaily:
    def source(self, nyse: Calendar, fetch: FakeFetch, pauses: list[float]) -> YFinanceSource:
        return YFinanceSource({"XNYS": nyse}, fetch=fetch, sleep=pauses.append)

    def test_asks_for_an_end_date_one_day_past_the_last_session(self, nyse: Calendar) -> None:
        fetch = FakeFetch([row(date(2024, 1, 2))])

        data = self.source(nyse, fetch, []).fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 5))

        assert fetch.calls == [("SPY", date(2024, 1, 2), date(2024, 1, 6))]
        assert len(data.bars) == 1

    def test_temporary_failures_are_retried_with_growing_pauses(self, nyse: Calendar) -> None:
        pauses: list[float] = []
        fetch = FakeFetch(
            TemporaryFailureError("rate limited"),
            TemporaryFailureError("timeout"),
            [row(date(2024, 1, 2))],
        )

        data = self.source(nyse, fetch, pauses).fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 2))

        assert len(fetch.calls) == 3
        assert pauses == [2.0, 4.0]
        assert len(data.bars) == 1

    def test_gives_up_after_the_last_attempt(self, nyse: Calendar) -> None:
        pauses: list[float] = []
        fetch = FakeFetch(*(TemporaryFailureError("rate limited") for _ in range(3)))

        with pytest.raises(DataError, match="failed for 'SPY' after 3 attempts: rate limited"):
            self.source(nyse, fetch, pauses).fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 2))

        assert pauses == [2.0, 4.0]

    def test_no_data_is_an_empty_answer_not_an_error(self, nyse: Calendar) -> None:
        fetch = FakeFetch(NoDataError("no price data found"))

        data = self.source(nyse, fetch, []).fetch_daily(SPY, date(2024, 1, 6), date(2024, 1, 7))

        assert data.bars == ()
        assert data.issues == ()

    def test_an_unknown_symbol_fails_at_once(self, nyse: Calendar) -> None:
        pauses: list[float] = []
        fetch = FakeFetch(UnknownSymbolError("no timezone found"))

        with pytest.raises(DataError, match="does not know the symbol 'SPY'"):
            self.source(nyse, fetch, pauses).fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 2))

        assert pauses == []

    def test_any_other_failure_is_not_retried(self, nyse: Calendar) -> None:
        fetch = FakeFetch(KeyError("Close"))

        with pytest.raises(DataError, match="Yahoo Finance failed for 'SPY'"):
            self.source(nyse, fetch, []).fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 2))

        assert len(fetch.calls) == 1

    def test_an_instrument_on_an_unloaded_calendar_is_an_error(self) -> None:
        source = YFinanceSource({}, fetch=FakeFetch())

        with pytest.raises(DataError, match="no calendar 'XNYS' loaded"):
            source.fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 2))

    def test_at_least_one_attempt(self, nyse: Calendar) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            YFinanceSource({"XNYS": nyse}, fetch=FakeFetch(), attempts=0)

    def test_describes_its_prices(self, nyse: Calendar) -> None:
        source = YFinanceSource({"XNYS": nyse}, fetch=FakeFetch())

        assert source.name == "yfinance"
        assert source.adjustment is PriceAdjustment.SPLITS


class TestRealFetcher:
    """The adapter around yfinance itself, with yfinance's network calls replaced."""

    def patch(self, monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        class FakeTicker:
            def __init__(self, ticker: str) -> None:
                self.ticker = ticker

            def history(self, **options: Any) -> Any:
                calls.append({"ticker": self.ticker, **options})
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
        return calls

    def test_asks_for_split_adjusted_daily_prices_with_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self.patch(monkeypatch, TestRowsFromFrame().frame(with_capital_gains=False))

        rows = yfinance_fetcher()("SPY", date(2024, 3, 14), date(2024, 3, 16))

        assert len(rows) == 2
        assert calls == [
            {
                "ticker": "SPY",
                "start": "2024-03-14",
                "end": "2024-03-16",
                "interval": "1d",
                "auto_adjust": False,
                "actions": True,
            }
        ]
        assert yfinance.config.debug.hide_exceptions is False

    @pytest.mark.parametrize(
        ("raised", "expected"),
        [
            (yfinance.exceptions.YFPricesMissingError("SPY", ""), NoDataError),
            (yfinance.exceptions.YFTzMissingError("ZZZZ"), UnknownSymbolError),
            (yfinance.exceptions.YFRateLimitError(), TemporaryFailureError),
        ],
        ids=["no data", "unknown symbol", "rate limit"],
    )
    def test_translates_yfinance_errors(
        self, monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: type[Exception]
    ) -> None:
        self.patch(monkeypatch, raised)

        with pytest.raises(expected):
            yfinance_fetcher()("SPY", date(2024, 1, 2), date(2024, 1, 3))

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(404, UnknownSymbolError), (429, TemporaryFailureError), (503, TemporaryFailureError)],
    )
    def test_http_errors_are_classified_by_status(
        self, monkeypatch: pytest.MonkeyPatch, status: int, expected: type[Exception]
    ) -> None:
        self.patch(monkeypatch, CurlHTTPError(f"HTTP {status}", response=FakeResponse(status)))

        with pytest.raises(expected, match=f"HTTP {status}"):
            yfinance_fetcher()("SPY", date(2024, 1, 2), date(2024, 1, 3))

    def test_other_http_errors_are_permanent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.patch(monkeypatch, RequestsHTTPError("HTTP 401", response=FakeResponse(401)))

        with pytest.raises(RequestsHTTPError, match="HTTP 401"):
            yfinance_fetcher()("SPY", date(2024, 1, 2), date(2024, 1, 3))

    def test_network_errors_are_temporary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

        self.patch(monkeypatch, CurlConnectionError("connection refused"))

        with pytest.raises(TemporaryFailureError, match="connection refused"):
            yfinance_fetcher()("SPY", date(2024, 1, 2), date(2024, 1, 3))

    def test_keeps_yfinances_own_cache_in_the_given_folder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        chosen: list[str] = []
        monkeypatch.setattr(yfinance, "set_tz_cache_location", chosen.append)

        yfinance_fetcher(tmp_path / "yfinance-cache")

        assert chosen == [str(tmp_path / "yfinance-cache")]
        assert (tmp_path / "yfinance-cache").is_dir()


@pytest.mark.network
def test_real_yahoo_data_for_a_known_dividend(nyse: Calendar, tmp_path: Path) -> None:
    """Opt-in: ``uv run pytest -m network``. Checks the facts the adapter relies on."""
    source = YFinanceSource({"XNYS": nyse}, fetch=yfinance_fetcher(tmp_path))

    data = source.fetch_daily(SPY, date(2024, 3, 12), date(2024, 3, 19))

    assert len(data.bars) == 6
    assert data.bars[0].timestamp == datetime(2024, 3, 12, 20, 0, tzinfo=UTC)
    assert [(d.ex_date, d.amount_per_share.amount) for d in data.distributions] == [
        (date(2024, 3, 15), Decimal("1.595"))
    ]

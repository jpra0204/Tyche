"""The Parquet bar cache: faithful round trips, upserts, coverage, and refusing bad files."""

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tyche.adapters.data import CacheEntry, DateRange, ParquetBarCache
from tyche.core.domain import Timeframe
from tyche.core.ports import DataError

FIRST_FETCH = datetime(2024, 1, 20, 12, 0, tzinfo=UTC)
SECOND_FETCH = datetime(2024, 2, 1, 12, 0, tzinfo=UTC)
DAYS = JANUARY_2024[:3]


@pytest.fixture
def cache(tmp_path: Path) -> ParquetBarCache:
    return ParquetBarCache(tmp_path / "data", source="test")


def entry_with(
    days: list[date], *, fetched_at: datetime = FIRST_FETCH, close: float = 100.0
) -> CacheEntry:
    return CacheEntry(SPY, Timeframe.D1).merged(
        [bar(day, close) for day in days],
        fetched_at=fetched_at,
        covered=DateRange(days[0], days[-1]),
        is_adjusted=True,
    )


class TestRoundTrip:
    def test_nothing_cached_gives_an_empty_entry(self, cache: ParquetBarCache) -> None:
        entry = cache.load(SPY, Timeframe.D1)

        assert entry == CacheEntry(SPY, Timeframe.D1)
        assert entry.is_adjusted is None
        assert entry.rows == ()

    def test_what_is_stored_is_what_is_loaded(self, cache: ParquetBarCache) -> None:
        entry = entry_with(DAYS)

        cache.store(entry)

        assert cache.load(SPY, Timeframe.D1) == entry

    def test_timestamps_come_back_in_utc(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))

        loaded = cache.load(SPY, Timeframe.D1)

        assert all(row.bar.timestamp.utcoffset() is not None for row in loaded.rows)
        assert loaded.rows[0].bar.timestamp == close_of(DAYS[0])
        assert loaded.rows[0].fetched_at == FIRST_FETCH

    def test_one_file_per_source_timeframe_and_instrument(
        self, cache: ParquetBarCache, tmp_path: Path
    ) -> None:
        cache.store(entry_with(DAYS))

        assert (
            cache.path_for(SPY, Timeframe.D1)
            == tmp_path / "data" / "test" / "1d" / "ARCX" / "SPY.parquet"
        )
        assert cache.path_for(SPY, Timeframe.D1).is_file()

    def test_storing_again_replaces_the_file_and_leaves_no_temporary_files(
        self, cache: ParquetBarCache
    ) -> None:
        cache.store(entry_with(DAYS))
        cache.store(entry_with(JANUARY_2024[:5]))

        folder = cache.path_for(SPY, Timeframe.D1).parent
        assert [p.name for p in folder.iterdir()] == ["SPY.parquet"]
        assert len(cache.load(SPY, Timeframe.D1).rows) == 5

    def test_an_empty_entry_is_never_written(self, cache: ParquetBarCache) -> None:
        with pytest.raises(DataError, match="refusing to store an empty cache entry"):
            cache.store(CacheEntry(SPY, Timeframe.D1))

    @pytest.mark.parametrize("name", ["", "Yahoo", "../x", "y finance"])
    def test_rejects_an_unsafe_source_name(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(ValueError, match="invalid source name"):
            ParquetBarCache(tmp_path, source=name)


class TestMerge:
    def test_a_newer_fetch_replaces_the_same_session_and_records_when(self) -> None:
        revised = entry_with(DAYS).merged(
            [bar(DAYS[1], close=101.5)], fetched_at=SECOND_FETCH, covered=None, is_adjusted=True
        )

        assert [row.bar.close for row in revised.rows] == [100.0, 101.5, 100.0]
        assert [row.fetched_at for row in revised.rows] == [FIRST_FETCH, SECOND_FETCH, FIRST_FETCH]

    def test_rows_stay_in_time_order(self) -> None:
        later_first = entry_with([DAYS[2]]).merged(
            [bar(DAYS[0])], fetched_at=SECOND_FETCH, covered=None, is_adjusted=True
        )

        assert [row.bar.timestamp for row in later_first.rows] == [
            close_of(DAYS[0]),
            close_of(DAYS[2]),
        ]

    def test_refuses_to_mix_adjusted_and_unadjusted_prices(self) -> None:
        with pytest.raises(DataError, match="holds adjusted prices; refusing to mix"):
            entry_with(DAYS).merged([], fetched_at=SECOND_FETCH, covered=None, is_adjusted=False)

    def test_refuses_a_bar_of_another_instrument(self) -> None:
        with pytest.raises(DataError, match="cannot cache a bar of QQQ@XNAS"):
            CacheEntry(SPY, Timeframe.D1).merged(
                [bar(DAYS[0], instrument=QQQ)],
                fetched_at=FIRST_FETCH,
                covered=None,
                is_adjusted=True,
            )

    def test_refuses_a_bar_whose_adjustment_does_not_match(self) -> None:
        with pytest.raises(DataError, match="wrong adjustment"):
            CacheEntry(SPY, Timeframe.D1).merged(
                [bar(DAYS[0], adjusted=False)],
                fetched_at=FIRST_FETCH,
                covered=None,
                is_adjusted=True,
            )

    def test_fetch_time_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            CacheEntry(SPY, Timeframe.D1).merged(
                [], fetched_at=FIRST_FETCH.replace(tzinfo=None), covered=None, is_adjusted=True
            )

    def test_bars_between_selects_by_timestamp_inclusive(self) -> None:
        entry = entry_with(JANUARY_2024[:5])

        rows = entry.bars_between(close_of(DAYS[1]), close_of(DAYS[2]))

        assert [row.bar.timestamp for row in rows] == [close_of(DAYS[1]), close_of(DAYS[2])]


class TestCoverage:
    def merge_ranges(self, *ranges: tuple[date, date]) -> tuple[DateRange, ...]:
        entry = CacheEntry(SPY, Timeframe.D1)
        for first, last in ranges:
            entry = entry.merged(
                [], fetched_at=FIRST_FETCH, covered=DateRange(first, last), is_adjusted=True
            )
        return entry.coverage

    def test_overlapping_ranges_merge(self) -> None:
        assert self.merge_ranges(
            (date(2024, 1, 2), date(2024, 1, 10)), (date(2024, 1, 5), date(2024, 1, 20))
        ) == (DateRange(date(2024, 1, 2), date(2024, 1, 20)),)

    def test_touching_ranges_merge(self) -> None:
        assert self.merge_ranges(
            (date(2024, 1, 2), date(2024, 1, 5)), (date(2024, 1, 6), date(2024, 1, 9))
        ) == (DateRange(date(2024, 1, 2), date(2024, 1, 9)),)

    def test_separate_ranges_stay_separate_and_sorted(self) -> None:
        assert self.merge_ranges(
            (date(2024, 2, 1), date(2024, 2, 5)), (date(2024, 1, 2), date(2024, 1, 5))
        ) == (
            DateRange(date(2024, 1, 2), date(2024, 1, 5)),
            DateRange(date(2024, 2, 1), date(2024, 2, 5)),
        )

    def test_covers(self) -> None:
        entry = entry_with(DAYS)

        assert entry.covers(DAYS[0])
        assert entry.covers(DAYS[2])
        assert not entry.covers(JANUARY_2024[3])

    def test_coverage_survives_a_round_trip(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))

        assert cache.load(SPY, Timeframe.D1).coverage == (DateRange(DAYS[0], DAYS[2]),)

    def test_an_empty_range_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty date range"):
            DateRange(date(2024, 1, 5), date(2024, 1, 2))


class TestBadFiles:
    def test_a_file_for_another_instrument_is_refused(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))
        target = cache.path_for(QQQ, Timeframe.D1)
        target.parent.mkdir(parents=True)
        shutil.copy(cache.path_for(SPY, Timeframe.D1), target)

        with pytest.raises(DataError, match="belongs to SPY@ARCX 1d, not QQQ@XNAS 1d"):
            cache.load(QQQ, Timeframe.D1)

    def test_a_corrupt_file_is_refused(self, cache: ParquetBarCache) -> None:
        path = cache.path_for(SPY, Timeframe.D1)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not parquet")

        with pytest.raises(DataError, match="cannot read cache file"):
            cache.load(SPY, Timeframe.D1)

    def test_a_file_from_a_future_format_says_how_to_recover(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))
        path = cache.path_for(SPY, Timeframe.D1)
        table = pq.read_table(path)
        metadata = json.loads(table.schema.metadata[b"tyche"])
        metadata["format"] = 99
        pq.write_table(
            table.replace_schema_metadata({b"tyche": json.dumps(metadata).encode()}), path
        )

        with pytest.raises(DataError, match=r"format 99.*Delete it and it will be fetched again"):
            cache.load(SPY, Timeframe.D1)

    def test_a_parquet_file_without_tyche_metadata_is_refused(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))
        path = cache.path_for(SPY, Timeframe.D1)
        pq.write_table(pq.read_table(path).replace_schema_metadata(None), path)

        with pytest.raises(DataError, match="has no Tyche metadata"):
            cache.load(SPY, Timeframe.D1)

    def test_a_file_with_other_columns_is_refused(self, cache: ParquetBarCache) -> None:
        path = cache.path_for(SPY, Timeframe.D1)
        path.parent.mkdir(parents=True)
        pq.write_table(pa.table({"price": [1.0]}), path)

        with pytest.raises(DataError, match="unexpected layout"):
            cache.load(SPY, Timeframe.D1)

    def test_an_impossible_bar_in_the_file_is_refused(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))
        path = cache.path_for(SPY, Timeframe.D1)
        table = pq.read_table(path)
        broken = table.set_column(
            table.schema.get_field_index("close"), "close", pa.array([100.0, -1.0, 100.0])
        )
        pq.write_table(broken, path)

        with pytest.raises(DataError, match="holds an invalid bar"):
            cache.load(SPY, Timeframe.D1)

    def test_unreadable_metadata_is_refused(self, cache: ParquetBarCache) -> None:
        cache.store(entry_with(DAYS))
        path = cache.path_for(SPY, Timeframe.D1)
        pq.write_table(pq.read_table(path).replace_schema_metadata({b"tyche": b"{not json"}), path)

        with pytest.raises(DataError, match="unreadable Tyche metadata"):
            cache.load(SPY, Timeframe.D1)


def test_a_failed_write_keeps_the_previous_file_and_cleans_up(
    cache: ParquetBarCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache.store(entry_with(DAYS))
    before = cache.load(SPY, Timeframe.D1)

    def disk_full(*args: object, **kwargs: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(pq, "write_table", disk_full)
    with pytest.raises(OSError, match="No space left"):
        cache.store(entry_with(JANUARY_2024[:5]))
    monkeypatch.undo()

    assert cache.load(SPY, Timeframe.D1) == before
    assert [p.name for p in cache.path_for(SPY, Timeframe.D1).parent.iterdir()] == ["SPY.parquet"]

"""Real runs through the SQLite journal: every event of every type comes back identical.

The journal's rows are never rewritten (ADR-0009), so what is stored must read back as
exactly the events that were published, whatever they carry: Decimals, UTC times,
enums, accounts keyed by instrument, the risk gate's cuts. Two years of the example
strategies produce most event types; ``rare_events`` adds the ones clean simulated
data does not.
"""

from contextlib import closing
from pathlib import Path

import pytest

import tyche.core.events
from tests.integration.test_example_strategies import GLD, TLT, run
from tests.support.events import rare_events
from tests.support.market import QQQ, SPY
from tests.support.risk import DEFAULT
from tyche.adapters.storage import SqliteJournalStore, open_database
from tyche.core.backtest import BacktestResult
from tyche.core.events import Event, RiskEvent
from tyche.core.pipeline.journal import JournalView
from tyche.strategies import MeanReversion, TrendRotation


@pytest.fixture(scope="module")
def runs() -> dict[str, BacktestResult]:
    return {
        "dips": run(MeanReversion((SPY, QQQ)), (SPY, QQQ)),
        "rotation-default": run(
            TrendRotation((SPY, QQQ, TLT, GLD), holdings=2), (SPY, QQQ, TLT, GLD), risk=DEFAULT
        ),
    }


def test_every_event_of_real_runs_reads_back_identical(
    runs: dict[str, BacktestResult], tmp_path: Path
) -> None:
    path = tmp_path / "state" / "tyche.db"
    with closing(open_database(path)) as connection:
        store = SqliteJournalStore(connection)
        for run_id, result in runs.items():
            for envelope in result.journal.entries:
                store.append(run_id, envelope)

    with closing(open_database(path)) as connection:
        store = SqliteJournalStore(connection)
        assert store.run_ids() == tuple(runs)
        for run_id, result in runs.items():
            assert store.read(run_id) == result.journal.entries


def test_a_stored_risk_cut_is_explained_back_to_the_data_that_started_its_cycle(
    runs: dict[str, BacktestResult], tmp_path: Path
) -> None:
    result = runs["rotation-default"]
    with closing(open_database(tmp_path / "tyche.db")) as connection:
        store = SqliteJournalStore(connection)
        for envelope in result.journal.entries:
            store.append("rotation", envelope)
        stored = JournalView(store.read("rotation"))

    chain = stored.causes_of(stored.of_type(RiskEvent)[0])

    assert chain == result.journal.causes_of(result.journal.of_type(RiskEvent)[0])
    assert [type(e.event).__name__ for e in chain][-1] == "DataReadyEvent"


def test_the_runs_and_the_rare_events_cover_every_event_type(
    runs: dict[str, BacktestResult],
) -> None:
    seen = {
        type(envelope.event) for result in runs.values() for envelope in result.journal.entries
    } | {type(event) for event in rare_events()}
    exported = {
        candidate
        for name in tyche.core.events.__all__
        if isinstance(candidate := getattr(tyche.core.events, name), type)
        and issubclass(candidate, Event)
        and candidate is not Event
    }

    assert exported <= seen, sorted(t.__name__ for t in exported - seen)

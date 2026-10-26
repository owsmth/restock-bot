from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts.seed_stores import seed
from scripts.simulate import purge_simulator, run_simulation
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from restock.db.models import Observation, ProductCategory, Source, SourceName
from restock.db.session import SessionFactory
from restock.repositories.sources import SourceRepository
from restock.repositories.stores import StoreRepository
from restock.services.reports import ReportService

pytestmark = pytest.mark.integration

EXAMPLE_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "stores_example.csv"


def test_simulation_persists_labeled_rows_and_purge_is_scoped(
    session_factory: SessionFactory,
    db_session: Session,
) -> None:
    seed(EXAMPLE_CSV_PATH, session_factory)

    stores = StoreRepository(db_session).list_active()
    target_id = next(store.id for store in stores if store.name == "EXAMPLE Target Cape Coral")
    user_service = ReportService(
        session_factory,
        reporter_hash_salt="test-salt-at-least-sixteen-characters",
        clock=lambda: datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
    )
    user_service.submit_report(
        reporter_id=1,
        store_id=target_id,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )

    result = run_simulation(
        session_factory,
        weeks=1,
        seed=42,
        end_date=date(2026, 1, 5),
    )
    assert result.observations

    simulator_source = SourceRepository(db_session).get_by_name(SourceName.SIMULATOR.value)
    assert simulator_source is not None
    simulator_count = db_session.scalar(
        select(func.count())
        .select_from(Observation)
        .where(Observation.source_id == simulator_source.id)
    )
    assert simulator_count == len(result.observations)

    sample_simulator_row = db_session.scalar(
        select(Observation).where(Observation.source_id == simulator_source.id).limit(1)
    )
    assert sample_simulator_row is not None
    assert sample_simulator_row.notes is not None
    assert sample_simulator_row.notes.startswith("SIMULATOR:")

    deleted = purge_simulator(session_factory)
    assert deleted == len(result.observations)

    remaining = list(db_session.scalars(select(Observation)))
    assert len(remaining) == 1
    assert remaining[0].reporter_hash is not None
    assert remaining[0].source_id != simulator_source.id

    source_rows = list(db_session.scalars(select(Source)))
    assert len(source_rows) == 3

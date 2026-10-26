from __future__ import annotations

from datetime import UTC, datetime

import pytest
from scripts.remove_example_data import EXAMPLE_STORE_PREFIX, main, remove_example_data
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from restock.db.models import (
    Observation,
    ObservationKind,
    ProductCategory,
    Retailer,
    Source,
    Store,
)
from restock.db.session import SessionFactory
from restock.repositories.observations import ObservationRepository, ObservationWrite
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository, StoreWrite

pytestmark = pytest.mark.integration


def _store(name: str, city: str) -> StoreWrite:
    return StoreWrite(
        retailer=Retailer.TARGET,
        name=name,
        address=f"{name} address",
        city=city,
        lat=26.5629,
        lng=-81.9495,
        timezone="America/New_York",
    )


def _observation(store_id: int, source_id: int, *, in_stock: bool) -> ObservationWrite:
    now = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    return ObservationWrite(
        kind=ObservationKind.REPORT,
        store_id=store_id,
        product_category=ProductCategory.ETB,
        in_stock=in_stock,
        observed_at=now,
        reported_at=now,
        source_id=source_id,
        reporter_hash="a" * 64,
    )


def test_remove_example_data_deletes_rows_in_fk_order(
    session_factory: SessionFactory,
    db_session: Session,
) -> None:
    source_repository = SourceRepository(db_session)
    discord = source_repository.upsert(
        SourceWrite(name="discord_report", trust_weight=0.65, compliance_note="Test")
    )[0]
    simulator = source_repository.upsert(
        SourceWrite(name="simulator", trust_weight=1.0, compliance_note="Test")
    )[0]
    store_repository = StoreRepository(db_session)
    example_store = store_repository.upsert(_store(f"{EXAMPLE_STORE_PREFIX} Target", "Cape Coral"))[
        0
    ]
    real_store = store_repository.upsert(_store("Target - Main St", "Fort Myers"))[0]
    observation_repository = ObservationRepository(db_session)
    observation_repository.create(_observation(example_store.id, discord.id, in_stock=True))
    observation_repository.create(_observation(example_store.id, simulator.id, in_stock=False))
    observation_repository.create(_observation(real_store.id, discord.id, in_stock=True))
    observation_repository.create(_observation(real_store.id, simulator.id, in_stock=False))
    db_session.commit()

    summary = remove_example_data(session_factory)

    assert summary.stores_before == 2
    assert summary.observations_before == 4
    assert summary.example_stores_targeted == 1
    assert summary.example_observations_targeted == 2
    assert summary.simulator_observations_targeted == 2
    assert summary.simulator_observations_deleted == 2
    assert summary.example_observations_deleted == 1
    assert summary.observations_deleted == 3
    assert summary.stores_deleted == 1
    assert summary.stores_after == 1
    assert summary.observations_after == 1

    db_session.expire_all()
    remaining_stores = list(db_session.scalars(select(Store)))
    remaining_observations = list(db_session.scalars(select(Observation)))
    assert [store.name for store in remaining_stores] == ["Target - Main St"]
    assert len(remaining_observations) == 1
    assert remaining_observations[0].source_id == discord.id
    assert db_session.scalar(select(func.count()).select_from(Source)) == 2


def test_remove_example_data_is_safe_when_nothing_matches(
    session_factory: SessionFactory,
    db_session: Session,
) -> None:
    StoreRepository(db_session).upsert(_store("Target - Main St", "Fort Myers"))
    db_session.commit()

    summary = remove_example_data(session_factory)

    assert summary.example_stores_targeted == 0
    assert summary.simulator_observations_targeted == 0
    assert summary.stores_deleted == 0
    assert summary.observations_deleted == 0
    assert summary.stores_after == 1


def test_cli_requires_yes_flag() -> None:
    assert main([]) == 2

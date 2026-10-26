from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from restock.db.models import (
    Observation,
    ObservationKind,
    ProductCategory,
    RestockRegime,
    Retailer,
    Store,
)
from restock.repositories.observations import ObservationRepository, ObservationWrite
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository, StoreWrite

pytestmark = pytest.mark.integration


def store_write(
    *,
    name: str = "EXAMPLE Target Cape Coral",
    city: str = "Cape Coral",
    active: bool = True,
) -> StoreWrite:
    return StoreWrite(
        retailer=Retailer.TARGET,
        name=name,
        address=f"{name} address",
        city=city,
        lat=26.5629,
        lng=-81.9495,
        timezone="America/New_York",
        restock_regime=RestockRegime.SCHEDULED,
        active=active,
    )


def test_store_upsert_is_idempotent_and_updates_fields(db_session: Session) -> None:
    repository = StoreRepository(db_session)

    first, first_created = repository.upsert(store_write())
    first_id = first.id
    db_session.commit()

    second, second_created = repository.upsert(store_write(city="Fort Myers"))
    db_session.commit()

    stores = list(db_session.scalars(select(Store)))
    assert first_created is True
    assert second_created is False
    assert second.id == first_id
    assert len(stores) == 1
    assert stores[0].city == "Fort Myers"


def test_store_queries_filter_and_search(db_session: Session) -> None:
    repository = StoreRepository(db_session)
    repository.upsert(store_write(name="EXAMPLE Target Cape Coral"))
    repository.upsert(store_write(name="EXAMPLE Target Fort Myers", city="Fort Myers"))
    repository.upsert(store_write(name="EXAMPLE Closed Store", active=False))
    db_session.commit()

    assert len(repository.list_active()) == 2
    assert len(repository.list_active(Retailer.WALMART)) == 0
    assert [store.city for store in repository.search_active("fort")] == ["Fort Myers"]
    assert [store.name for store in repository.search_active("cape")] == [
        "EXAMPLE Target Cape Coral"
    ]
    assert repository.search_active("%") == []
    assert repository.search_active("Cape", limit=1)[0].name == "EXAMPLE Target Cape Coral"
    assert repository.get(999999) is None


def test_observation_recent_and_filter(db_session: Session) -> None:
    store = StoreRepository(db_session).upsert(store_write())[0]
    source = SourceRepository(db_session).upsert(
        SourceWrite(
            name="discord_report",
            trust_weight=0.65,
            compliance_note="Test source",
        )
    )[0]
    db_session.commit()

    repository = ObservationRepository(db_session)
    now = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    for index, category in enumerate(
        [ProductCategory.ETB, ProductCategory.BOOSTER_BOX, ProductCategory.ETB]
    ):
        repository.create(
            ObservationWrite(
                kind=ObservationKind.REPORT,
                store_id=store.id,
                product_category=category,
                in_stock=True,
                observed_at=now - timedelta(hours=index),
                reported_at=now,
                source_id=source.id,
                reporter_hash=f"{index:064x}",
            )
        )
    db_session.commit()

    recent = repository.list_recent(store_id=store.id)
    assert len(recent) == 3
    assert [item.product_category for item in recent] == [
        ProductCategory.ETB,
        ProductCategory.BOOSTER_BOX,
        ProductCategory.ETB,
    ]

    etb_recent = repository.list_recent(
        store_id=store.id,
        product_category=ProductCategory.ETB,
        limit=1,
    )
    assert len(etb_recent) == 1
    assert etb_recent[0].in_stock is True


def test_observation_duplicate_lookup(db_session: Session) -> None:
    store = StoreRepository(db_session).upsert(store_write())[0]
    source = SourceRepository(db_session).upsert(
        SourceWrite(name="discord_report", trust_weight=0.65, compliance_note="Test")
    )[0]
    db_session.commit()

    repository = ObservationRepository(db_session)
    now = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    reporter_hash = "a" * 64
    repository.create(
        ObservationWrite(
            kind=ObservationKind.REPORT,
            store_id=store.id,
            product_category=ProductCategory.ETB,
            in_stock=True,
            observed_at=now - timedelta(minutes=10),
            reported_at=now,
            source_id=source.id,
            reporter_hash=reporter_hash,
        )
    )
    db_session.commit()

    assert repository.has_recent_duplicate(
        reporter_hash=reporter_hash,
        store_id=store.id,
        product_category=ProductCategory.ETB,
        in_stock=True,
        submitted_since=now - timedelta(minutes=30),
    )
    assert not repository.has_recent_duplicate(
        reporter_hash=reporter_hash,
        store_id=store.id,
        product_category=ProductCategory.ETB,
        in_stock=False,
        submitted_since=now - timedelta(minutes=30),
    )
    assert not repository.has_recent_duplicate(
        reporter_hash=reporter_hash,
        store_id=store.id,
        product_category=ProductCategory.ETB,
        in_stock=True,
        submitted_since=now + timedelta(seconds=1),
    )


def test_delete_by_source_only_deletes_that_source(
    db_session: Session,
    seeded_store: int,
) -> None:
    source_repository = SourceRepository(db_session)
    discord = source_repository.upsert(
        SourceWrite(name="discord_report", trust_weight=0.65, compliance_note="Test")
    )[0]
    simulator = source_repository.upsert(
        SourceWrite(name="simulator", trust_weight=1.0, compliance_note="Test")
    )[0]
    db_session.commit()

    observation_repository = ObservationRepository(db_session)
    now = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    for source_id in (discord.id, simulator.id):
        observation_repository.create(
            ObservationWrite(
                kind=ObservationKind.REPORT,
                store_id=seeded_store,
                product_category=ProductCategory.ETB,
                in_stock=True,
                observed_at=now,
                reported_at=now,
                source_id=source_id,
                reporter_hash=None,
            )
        )
    db_session.commit()

    assert observation_repository.delete_by_source(simulator.id) == 1
    db_session.commit()

    remaining = list(db_session.scalars(select(Observation)))
    assert len(remaining) == 1
    assert remaining[0].source_id == discord.id

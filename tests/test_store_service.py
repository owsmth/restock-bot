from __future__ import annotations

import pytest

from restock.db.models import Retailer
from restock.db.session import SessionFactory, session_scope
from restock.repositories.stores import StoreRepository, StoreWrite
from restock.services.errors import StoreInactiveError, StoreNotFoundError
from restock.services.stores import StoreService

pytestmark = pytest.mark.integration


@pytest.fixture
def store_service(session_factory: SessionFactory) -> StoreService:
    with session_scope(session_factory) as session:
        repository = StoreRepository(session)
        repository.upsert(
            StoreWrite(
                retailer=Retailer.TARGET,
                name="EXAMPLE Target Cape Coral",
                address="1 Example Retail Way",
                city="Cape Coral",
                lat=26.5629,
                lng=-81.9495,
                timezone="America/New_York",
            )
        )
        repository.upsert(
            StoreWrite(
                retailer=Retailer.WALMART,
                name="EXAMPLE Walmart Fort Myers",
                address="2 Example Retail Way",
                city="Fort Myers",
                lat=26.6406,
                lng=-81.8723,
                timezone="America/New_York",
                active=False,
            )
        )
    return StoreService(session_factory)


def test_list_active_filters_retailer(store_service: StoreService) -> None:
    assert len(store_service.list_active()) == 1
    assert store_service.list_active(Retailer.TARGET)[0].city == "Cape Coral"
    assert store_service.list_active(Retailer.WALMART) == []


def test_search_is_case_insensitive(store_service: StoreService) -> None:
    results = store_service.search_active("cape")
    assert [store.name for store in results] == ["EXAMPLE Target Cape Coral"]
    assert store_service.search_active("FORT") == []


def test_get_active_rejects_missing_and_inactive(store_service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        store_service.get_active(999_999)
    with pytest.raises(StoreInactiveError):
        store_service.get_active(2)

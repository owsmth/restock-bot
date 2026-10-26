from __future__ import annotations

from dataclasses import dataclass

from restock.db.models import RestockRegime, Retailer, Store
from restock.db.session import SessionFactory, session_scope
from restock.repositories.stores import StoreRepository
from restock.services.errors import StoreInactiveError, StoreNotFoundError


@dataclass(frozen=True, slots=True)
class StoreSummary:
    id: int
    retailer: Retailer
    name: str
    address: str
    city: str
    timezone: str
    restock_regime: RestockRegime

    @classmethod
    def from_model(cls, store: Store) -> StoreSummary:
        return cls(
            id=store.id,
            retailer=store.retailer,
            name=store.name,
            address=store.address,
            city=store.city,
            timezone=store.timezone,
            restock_regime=store.restock_regime,
        )


class StoreService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def list_active(self, retailer: Retailer | None = None) -> list[StoreSummary]:
        with session_scope(self._session_factory) as session:
            stores = StoreRepository(session).list_active(retailer)
            return [StoreSummary.from_model(store) for store in stores]

    def search_active(self, query: str, *, limit: int = 25) -> list[StoreSummary]:
        with session_scope(self._session_factory) as session:
            stores = StoreRepository(session).search_active(query, limit=limit)
            return [StoreSummary.from_model(store) for store in stores]

    def get_active(self, store_id: int) -> StoreSummary:
        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).get(store_id)
            if store is None:
                raise StoreNotFoundError(store_id)
            if not store.active:
                raise StoreInactiveError(store.name)
            return StoreSummary.from_model(store)

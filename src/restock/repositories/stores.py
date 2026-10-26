from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from restock.db.models import RestockRegime, Retailer, Store


@dataclass(frozen=True, slots=True)
class StoreWrite:
    retailer: Retailer
    name: str
    address: str
    city: str
    lat: float
    lng: float
    timezone: str
    restock_regime: RestockRegime = RestockRegime.UNKNOWN
    active: bool = True


class StoreRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, store_id: int, *, active_only: bool = False) -> Store | None:
        statement = select(Store).where(Store.id == store_id)
        if active_only:
            statement = statement.where(Store.active.is_(True))
        return self._session.scalar(statement)

    def list_active(self, retailer: Retailer | None = None) -> list[Store]:
        statement = select(Store).where(Store.active.is_(True))
        if retailer is not None:
            statement = statement.where(Store.retailer == retailer)
        return list(self._session.scalars(statement.order_by(Store.name)))

    def search_active(self, query: str, *, limit: int = 25) -> list[Store]:
        normalized = query.strip()
        statement = select(Store).where(Store.active.is_(True))
        if normalized:
            statement = statement.where(
                or_(
                    Store.name.icontains(normalized, autoescape=True),
                    Store.city.icontains(normalized, autoescape=True),
                )
            )
        return list(self._session.scalars(statement.order_by(Store.name).limit(limit)))

    def upsert(self, values: StoreWrite) -> tuple[Store, bool]:
        store = self._session.scalar(
            select(Store).where(
                Store.retailer == values.retailer,
                Store.name == values.name,
                Store.address == values.address,
            )
        )
        if store is None:
            store = Store(
                retailer=values.retailer,
                name=values.name,
                address=values.address,
                city=values.city,
                lat=values.lat,
                lng=values.lng,
                timezone=values.timezone,
                restock_regime=values.restock_regime,
                active=values.active,
            )
            self._session.add(store)
            self._session.flush()
            return store, True

        store.city = values.city
        store.lat = values.lat
        store.lng = values.lng
        store.timezone = values.timezone
        store.restock_regime = values.restock_regime
        store.active = values.active
        self._session.flush()
        return store, False

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
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

    def get(self, store_id: int) -> Store | None:
        return self._session.scalar(select(Store).where(Store.id == store_id))

    def list_active(self, retailer: Retailer | None = None) -> list[Store]:
        statement = select(Store).where(Store.active.is_(True))
        if retailer is not None:
            statement = statement.where(Store.retailer == retailer)
        return list(self._session.scalars(statement.order_by(Store.name)))

    def list_by_name_prefix(self, prefix: str) -> list[Store]:
        return list(
            self._session.scalars(
                select(Store)
                .where(Store.name.startswith(prefix, autoescape=True))
                .order_by(Store.id)
            )
        )

    def count_all(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(Store)) or 0)

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

    def delete_ids(self, store_ids: list[int]) -> int:
        if not store_ids:
            return 0
        result = self._session.execute(
            delete(Store).where(Store.id.in_(store_ids)).returning(Store.id)
        )
        return len(result.all())

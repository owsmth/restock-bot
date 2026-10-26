from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from restock.db.models import Observation, ObservationKind, ProductCategory


@dataclass(frozen=True, slots=True)
class ObservationWrite:
    kind: ObservationKind
    store_id: int
    product_category: ProductCategory
    in_stock: bool
    observed_at: datetime
    reported_at: datetime
    source_id: int
    reporter_hash: str | None
    quantity_estimate: int | None = None
    notes: str | None = None


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, values: ObservationWrite) -> Observation:
        observation = Observation(
            kind=values.kind,
            store_id=values.store_id,
            product_category=values.product_category,
            in_stock=values.in_stock,
            observed_at=values.observed_at,
            reported_at=values.reported_at,
            source_id=values.source_id,
            reporter_hash=values.reporter_hash,
            quantity_estimate=values.quantity_estimate,
            notes=values.notes,
        )
        self._session.add(observation)
        self._session.flush()
        return observation

    def bulk_create(self, values: Sequence[ObservationWrite]) -> int:
        observations = [
            Observation(
                kind=item.kind,
                store_id=item.store_id,
                product_category=item.product_category,
                in_stock=item.in_stock,
                observed_at=item.observed_at,
                reported_at=item.reported_at,
                source_id=item.source_id,
                reporter_hash=item.reporter_hash,
                quantity_estimate=item.quantity_estimate,
                notes=item.notes,
            )
            for item in values
        ]
        self._session.add_all(observations)
        self._session.flush()
        return len(observations)

    def has_recent_duplicate(
        self,
        *,
        reporter_hash: str,
        store_id: int,
        product_category: ProductCategory,
        in_stock: bool,
        submitted_since: datetime,
    ) -> bool:
        statement = (
            select(Observation.id)
            .where(
                Observation.reporter_hash == reporter_hash,
                Observation.store_id == store_id,
                Observation.product_category == product_category,
                Observation.in_stock.is_(in_stock),
                Observation.reported_at >= submitted_since,
            )
            .limit(1)
        )
        return self._session.scalar(statement) is not None

    def list_recent(
        self,
        *,
        store_id: int,
        product_category: ProductCategory | None = None,
        limit: int = 10,
    ) -> list[Observation]:
        statement = select(Observation).where(Observation.store_id == store_id)
        if product_category is not None:
            statement = statement.where(Observation.product_category == product_category)
        statement = statement.order_by(
            Observation.observed_at.desc(),
            Observation.id.desc(),
        ).limit(limit)
        return list(self._session.scalars(statement))

    def delete_by_source(self, source_id: int) -> int:
        result = self._session.execute(
            delete(Observation).where(Observation.source_id == source_id).returning(Observation.id)
        )
        return len(result.all())

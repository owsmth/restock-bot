from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from restock.db.models import (
    Observation,
    ObservationKind,
    ProductCategory,
    ReportOutcome,
    ReportSource,
    Source,
)


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observation: Observation
    source_name: str


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    store_id: int
    outcome: ReportOutcome
    observed_at: datetime


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
    outcome: ReportOutcome | None = None
    quantity_estimate: int | None = None
    quantity_note: str | None = None
    raw_text: str | None = None
    notes: str | None = None
    report_source: ReportSource = ReportSource.DROPDOWN


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, values: ObservationWrite) -> Observation:
        observation = Observation(
            kind=values.kind,
            store_id=values.store_id,
            product_category=values.product_category,
            in_stock=values.in_stock,
            outcome=values.outcome,
            observed_at=values.observed_at,
            reported_at=values.reported_at,
            source_id=values.source_id,
            reporter_hash=values.reporter_hash,
            quantity_estimate=values.quantity_estimate,
            quantity_note=values.quantity_note,
            raw_text=values.raw_text,
            notes=values.notes,
            report_source=values.report_source,
        )
        self._session.add(observation)
        self._session.flush()
        return observation

    def get(self, observation_id: int) -> Observation | None:
        return self._session.get(Observation, observation_id)

    def bulk_create(self, values: Sequence[ObservationWrite]) -> int:
        observations = [
            Observation(
                kind=item.kind,
                store_id=item.store_id,
                product_category=item.product_category,
                in_stock=item.in_stock,
                outcome=item.outcome,
                observed_at=item.observed_at,
                reported_at=item.reported_at,
                source_id=item.source_id,
                reporter_hash=item.reporter_hash,
                quantity_estimate=item.quantity_estimate,
                quantity_note=item.quantity_note,
                raw_text=item.raw_text,
                notes=item.notes,
                report_source=item.report_source,
            )
            for item in values
        ]
        self._session.add_all(observations)
        self._session.flush()
        return len(observations)

    def lock_report_identity(
        self,
        *,
        reporter_hash: str,
        store_id: int,
        outcome: ReportOutcome,
    ) -> None:
        lock_key = f"{reporter_hash}:{store_id}:{outcome.value}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    def lock_reporter(self, reporter_hash: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"reporter:{reporter_hash}"},
        )

    def count_recent_by_reporter(
        self,
        *,
        reporter_hash: str,
        submitted_since: datetime,
        source_id: int,
    ) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(
                    Observation.reporter_hash == reporter_hash,
                    Observation.source_id == source_id,
                    Observation.reported_at >= submitted_since,
                )
            )
            or 0
        )

    def has_recent_duplicate(
        self,
        *,
        reporter_hash: str,
        store_id: int,
        outcome: ReportOutcome,
        submitted_since: datetime,
    ) -> bool:
        statement = (
            select(Observation.id)
            .where(
                Observation.reporter_hash == reporter_hash,
                Observation.store_id == store_id,
                Observation.outcome == outcome,
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
    ) -> list[ObservationRecord]:
        statement = (
            select(Observation, Source.name)
            .join(Source, Source.id == Observation.source_id)
            .where(
                Observation.store_id == store_id,
                Observation.report_source != ReportSource.IMPORTED,
            )
        )
        if product_category is not None:
            statement = statement.where(Observation.product_category == product_category)
        statement = statement.order_by(
            Observation.observed_at.desc(),
            Observation.id.desc(),
        ).limit(limit)
        return [
            ObservationRecord(observation=observation, source_name=source_name)
            for observation, source_name in self._session.execute(statement)
        ]

    def list_outcomes(
        self,
        *,
        store_id: int,
        start: datetime,
        end: datetime,
    ) -> list[OutcomeObservation]:
        statement = (
            select(Observation.store_id, Observation.outcome, Observation.observed_at)
            .where(
                Observation.store_id == store_id,
                Observation.outcome.in_([ReportOutcome.JUST_DROPPED, ReportOutcome.SOLD_OUT]),
                Observation.observed_at >= start,
                Observation.observed_at < end,
            )
            .order_by(Observation.observed_at, Observation.id)
        )
        return [
            OutcomeObservation(
                store_id=row.store_id,
                outcome=row.outcome,
                observed_at=row.observed_at,
            )
            for row in self._session.execute(statement)
            if row.outcome is not None
        ]

    def count_all(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(Observation)) or 0)

    def count_by_source(self, source_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.source_id == source_id)
            )
            or 0
        )

    def count_by_store_ids(self, store_ids: Sequence[int]) -> int:
        if not store_ids:
            return 0
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.store_id.in_(store_ids))
            )
            or 0
        )

    def delete_by_source(self, source_id: int) -> int:
        result = self._session.execute(
            delete(Observation).where(Observation.source_id == source_id).returning(Observation.id)
        )
        return len(result.all())

    def delete_by_store_ids(self, store_ids: Sequence[int]) -> int:
        if not store_ids:
            return 0
        result = self._session.execute(
            delete(Observation).where(Observation.store_id.in_(store_ids)).returning(Observation.id)
        )
        return len(result.all())

    def delete_by_id(self, observation_id: int) -> bool:
        result = self._session.execute(
            delete(Observation).where(Observation.id == observation_id).returning(Observation.id)
        )
        return result.first() is not None

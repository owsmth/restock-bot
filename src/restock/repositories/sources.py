from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from restock.db.models import Source


@dataclass(frozen=True, slots=True)
class SourceWrite:
    name: str
    trust_weight: float
    compliance_note: str


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_name(self, name: str) -> Source | None:
        return self._session.scalar(select(Source).where(Source.name == name))

    def upsert(self, values: SourceWrite) -> tuple[Source, bool]:
        source = self.get_by_name(values.name)
        if source is None:
            source = Source(
                name=values.name,
                trust_weight=values.trust_weight,
                compliance_note=values.compliance_note,
            )
            self._session.add(source)
            self._session.flush()
            return source, True

        source.trust_weight = values.trust_weight
        source.compliance_note = values.compliance_note
        self._session.flush()
        return source, False

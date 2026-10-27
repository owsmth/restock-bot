from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from restock.db.models import ProductCategory, ReportOutcome
from restock.services.stores import StoreSummary


@dataclass(frozen=True, slots=True)
class ParsedReport:
    store_id: int | None
    outcome: ReportOutcome | None
    products: ProductCategory | None = None
    quantity_note: str | None = None
    confidence: float = 0.0
    needs_clarification: str | None = None


class ReportParser(Protocol):
    def parse(self, text: str, stores: Sequence[StoreSummary]) -> ParsedReport: ...

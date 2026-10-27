from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from restock.config import get_settings
from restock.db.engine import create_db_engine
from restock.db.models import (
    ObservationKind,
    ProductCategory,
    ReportOutcome,
    ReportSource,
)
from restock.db.session import SessionFactory, create_session_factory, session_scope
from restock.logging import configure_logging
from restock.repositories.observations import ObservationRepository, ObservationWrite
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository
from restock.services.reports import outcome_in_stock

REQUIRED_COLUMNS = (
    "observed_at_et",
    "retailer",
    "store_hint",
    "event",
    "products",
    "note",
    "source",
    "confidence",
)
SKIP_EVENTS = {"schedule_info"}
EVENT_OUTCOMES = {
    "restock": ReportOutcome.JUST_DROPPED,
    "in_stock": ReportOutcome.IN_STOCK,
    "out_of_stock": ReportOutcome.SOLD_OUT,
    "none": ReportOutcome.NOTHING_HERE,
}
PRODUCT_ALIASES = {
    "booster box": ProductCategory.BOOSTER_BOX,
    "boosterbox": ProductCategory.BOOSTER_BOX,
    "etb": ProductCategory.ETB,
    "elite trainer box": ProductCategory.ETB,
    "elite trainer box etb": ProductCategory.ETB,
    "booster bundle": ProductCategory.BOOSTER_BUNDLE,
    "boosterbundle": ProductCategory.BOOSTER_BUNDLE,
    "blister": ProductCategory.BLISTER,
    "blister pack": ProductCategory.BLISTER,
    "tin": ProductCategory.TIN,
    "collection box": ProductCategory.COLLECTION_BOX,
    "collectionbox": ProductCategory.COLLECTION_BOX,
    "other": ProductCategory.OTHER,
}
DEFAULT_CONFIDENCE = 0.5
MAX_NOTE_LENGTH = 280


@dataclass(frozen=True, slots=True)
class ImportRow:
    line: int
    observed_at: datetime
    store_id: int
    outcome: ReportOutcome
    product_category: ProductCategory
    notes: str | None
    raw_text: str
    source_name: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ImportPlan:
    rows: tuple[ImportRow, ...]
    total_rows: int
    skipped_schedule_info: int
    skipped_blank_date: int
    unmatched_hints: tuple[str, ...]
    errors: tuple[str, ...]
    sources: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ImportSummary:
    total_rows: int
    importable_rows: int
    skipped_schedule_info: int
    skipped_blank_date: int
    unmatched_hints: tuple[str, ...]
    errors: tuple[str, ...]
    written: int
    dry_run: bool


def normalize_hint(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def load_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError("CSV has no header row.")
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError("CSV is missing columns: " + ", ".join(missing))

        rows: list[tuple[int, dict[str, str]]] = []
        for line, row in enumerate(reader, start=2):
            values = {key: (value or "").strip() for key, value in row.items() if key is not None}
            rows.append((line, values))
        return rows


def load_mapping(path: Path) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError("Mapping CSV has no header row.")
        missing = [column for column in ("store_hint", "store_id") if column not in fieldnames]
        if missing:
            raise ValueError("Mapping CSV is missing columns: " + ", ".join(missing))

        mapping: dict[str, int] = {}
        for line, row in enumerate(reader, start=2):
            hint = (row.get("store_hint") or "").strip()
            store_id_text = (row.get("store_id") or "").strip()
            if not hint or not store_id_text:
                continue
            try:
                store_id = int(store_id_text)
            except ValueError as exc:
                raise ValueError(f"Mapping line {line}: store_id must be an integer.") from exc
            key = normalize_hint(hint)
            existing = mapping.get(key)
            if existing is not None and existing != store_id:
                raise ValueError(f"Mapping line {line}: duplicate hint with a different store ID.")
            mapping[key] = store_id
        return mapping


def parse_observed_at(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def parse_confidence(value: str) -> float:
    if not value:
        return DEFAULT_CONFIDENCE
    confidence = float(value)
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1.")
    return confidence


def product_category_from_text(value: str) -> ProductCategory:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    if not normalized:
        return ProductCategory.OTHER
    direct = PRODUCT_ALIASES.get(normalized)
    if direct is not None:
        return direct

    tokens = [token for token in re.split(r"[,;/|]+", value) if token.strip()]
    token_categories: set[ProductCategory] = set()
    for token in tokens:
        category = PRODUCT_ALIASES.get(re.sub(r"[^a-z0-9]+", " ", token.casefold()).strip())
        if category is not None:
            token_categories.add(category)
    if len(token_categories) == 1:
        return next(iter(token_categories))

    matches = {category for alias, category in PRODUCT_ALIASES.items() if alias in normalized}
    if len(matches) == 1:
        return next(iter(matches))
    return ProductCategory.OTHER


def source_name(value: str) -> str:
    base = f"csv:{value.strip() or 'unknown'}"
    if len(base) <= 50:
        return base
    digest = hashlib.sha256(base.encode()).hexdigest()[:8]
    return f"{base[:41]}-{digest}"


def build_plan(
    rows: Sequence[tuple[int, dict[str, str]]],
    mapping: Mapping[str, int],
    known_store_ids: set[int],
) -> ImportPlan:
    imported: list[ImportRow] = []
    unmatched: set[str] = set()
    errors: list[str] = []
    source_confidence: dict[str, float] = {}
    skipped_schedule_info = 0
    skipped_blank_date = 0

    for line, row in rows:
        event = row["event"].strip().casefold()
        if event in SKIP_EVENTS:
            skipped_schedule_info += 1
            continue

        observed_text = row["observed_at_et"]
        if not observed_text:
            skipped_blank_date += 1
            continue

        try:
            observed_at = parse_observed_at(observed_text, ZoneInfo("America/New_York"))
        except ValueError:
            errors.append(f"Line {line}: invalid observed_at_et: {observed_text!r}")
            continue

        try:
            outcome = EVENT_OUTCOMES[event]
        except KeyError:
            errors.append(f"Line {line}: unknown event: {row['event']!r}")
            continue

        hint = row["store_hint"]
        if not hint:
            unmatched.add("(blank store_hint)")
            continue
        store_id = mapping.get(normalize_hint(hint))
        if store_id is None:
            unmatched.add(hint)
            continue
        if store_id not in known_store_ids:
            errors.append(f"Line {line}: mapping points to missing store ID {store_id}.")
            continue

        try:
            confidence = parse_confidence(row["confidence"])
        except ValueError:
            errors.append(f"Line {line}: invalid confidence: {row['confidence']!r}")
            continue

        product_category = product_category_from_text(row["products"])
        note = row["note"] or None
        notes = note[:MAX_NOTE_LENGTH] if note else None
        imported_source = source_name(row["source"])
        raw_text = (
            f"products={row['products']!r}; note={note!r}; "
            f"retailer={row['retailer']!r}; source={row['source']!r}; "
            f"confidence={confidence:g}"
        )
        imported.append(
            ImportRow(
                line=line,
                observed_at=observed_at,
                store_id=store_id,
                outcome=outcome,
                product_category=product_category,
                notes=notes,
                raw_text=raw_text,
                source_name=imported_source,
                confidence=confidence,
            )
        )
        source_confidence[imported_source] = max(
            source_confidence.get(imported_source, 0.0),
            confidence,
        )

    return ImportPlan(
        rows=tuple(imported),
        total_rows=len(rows),
        skipped_schedule_info=skipped_schedule_info,
        skipped_blank_date=skipped_blank_date,
        unmatched_hints=tuple(sorted(unmatched)),
        errors=tuple(errors),
        sources=source_confidence,
    )


def import_csv(
    session_factory: SessionFactory,
    csv_path: Path,
    mapping_path: Path,
    *,
    dry_run: bool = False,
) -> ImportSummary:
    rows = load_rows(csv_path)
    mapping = load_mapping(mapping_path)
    with session_scope(session_factory) as session:
        known_store_ids = {store.id for store in StoreRepository(session).list_all()}

    plan = build_plan(rows, mapping, known_store_ids)
    summary = ImportSummary(
        total_rows=plan.total_rows,
        importable_rows=len(plan.rows),
        skipped_schedule_info=plan.skipped_schedule_info,
        skipped_blank_date=plan.skipped_blank_date,
        unmatched_hints=plan.unmatched_hints,
        errors=plan.errors,
        written=0,
        dry_run=dry_run,
    )
    if dry_run or plan.errors or plan.unmatched_hints or not plan.rows:
        return summary

    with session_scope(session_factory) as session:
        source_repository = SourceRepository(session)
        source_ids: dict[str, int] = {}
        for name, confidence in plan.sources.items():
            source, _ = source_repository.upsert(
                SourceWrite(
                    name=name,
                    trust_weight=confidence,
                    compliance_note=("Operator-supplied CSV import; not user-generated."),
                )
            )
            source_ids[name] = source.id

        writes = [
            ObservationWrite(
                kind=ObservationKind.REPORT,
                store_id=row.store_id,
                product_category=row.product_category,
                in_stock=outcome_in_stock(row.outcome),
                outcome=row.outcome,
                observed_at=row.observed_at,
                reported_at=row.observed_at,
                source_id=source_ids[row.source_name],
                reporter_hash=None,
                quantity_note=None,
                raw_text=row.raw_text,
                notes=row.notes,
                report_source=ReportSource.IMPORTED,
            )
            for row in plan.rows
        ]
        ObservationRepository(session).bulk_create(writes)

    return replace(summary, written=len(plan.rows))


def print_summary(summary: ImportSummary) -> None:
    print(f"Rows: {summary.total_rows}")
    print(f"Importable: {summary.importable_rows}")
    print(f"Skipped schedule_info: {summary.skipped_schedule_info}")
    print(f"Skipped blank date: {summary.skipped_blank_date}")
    print(f"Written: {summary.written}")
    if summary.dry_run:
        print("Dry run: no rows written.")
    if summary.unmatched_hints:
        print(f"Unmatched store hints ({len(summary.unmatched_hints)}):")
        for hint in summary.unmatched_hints:
            print(f"  {hint}")
    if summary.errors:
        print(f"Errors ({len(summary.errors)}):")
        for error in summary.errors:
            print(f"  {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import observations from an operator-reviewed CSV."
    )
    parser.add_argument("--csv", type=Path, required=True, help="Input observations CSV")
    parser.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="CSV with store_hint and store_id columns",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report counts without writing",
    )
    arguments = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    try:
        summary = import_csv(
            create_session_factory(engine),
            arguments.csv,
            arguments.mapping,
            dry_run=arguments.dry_run,
        )
    except (OSError, ValueError, SQLAlchemyError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print_summary(summary)
    if summary.errors or summary.unmatched_hints:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

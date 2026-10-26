from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from restock.config import get_settings
from restock.db.engine import create_db_engine
from restock.db.models import RestockRegime, Retailer, SourceName
from restock.db.session import SessionFactory, create_session_factory, session_scope
from restock.logging import configure_logging
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository, StoreWrite

DEFAULT_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "stores_seed.csv"

SEED_SOURCES: tuple[SourceWrite, ...] = (
    SourceWrite(
        name=SourceName.DISCORD_REPORT.value,
        trust_weight=0.65,
        compliance_note=(
            "Submitted by authenticated Discord users through this bot; "
            "unverified crowdsourced report."
        ),
    ),
    SourceWrite(
        name=SourceName.SIMULATOR.value,
        trust_weight=1.0,
        compliance_note=(
            "Synthetic data generated only by scripts/simulate.py; not a real-world observation."
        ),
    ),
    SourceWrite(
        name=SourceName.MANUAL_LOG.value,
        trust_weight=0.9,
        compliance_note=(
            "Operator-entered observation used for manual reconciliation; not user-generated."
        ),
    ),
)


class StoreSeedRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    retailer: Retailer
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=100)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=64)
    restock_regime: RestockRegime = RestockRegime.UNKNOWN
    active: bool = True

    @field_validator("lat", "lng", mode="before")
    @classmethod
    def validate_optional_coordinate(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> StoreSeedRow:
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must both be set or both be blank")
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value


@dataclass(frozen=True, slots=True)
class SeedSummary:
    stores_created: int
    stores_updated: int
    sources_created: int
    sources_updated: int

    @property
    def stores_total(self) -> int:
        return self.stores_created + self.stores_updated


def load_seed_rows(path: Path) -> list[StoreSeedRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    if not raw_rows:
        raise ValueError(f"{path} contains no store rows")

    rows: list[StoreSeedRow] = []
    seen: dict[tuple[Retailer, str, str], int] = {}
    duplicates: list[str] = []
    for line_number, raw_row in enumerate(raw_rows, start=2):
        row = StoreSeedRow.model_validate(raw_row)
        identity = (row.retailer, row.name, row.address)
        if identity in seen:
            duplicates.append(
                f"line {line_number} duplicates line {seen[identity]}: "
                f"{row.retailer.value} | {row.name} | {row.address}"
            )
        else:
            seen[identity] = line_number
        rows.append(row)
    if duplicates:
        details = "\n".join(duplicates)
        raise ValueError(f"{path} contains duplicate store identities:\n{details}")
    return rows


def seed(path: Path, session_factory: SessionFactory) -> SeedSummary:
    rows = load_seed_rows(path)
    stores_created = 0
    stores_updated = 0
    sources_created = 0
    sources_updated = 0

    with session_scope(session_factory) as session:
        source_repository = SourceRepository(session)
        for source in SEED_SOURCES:
            _, created = source_repository.upsert(source)
            sources_created += int(created)
            sources_updated += int(not created)

        store_repository = StoreRepository(session)
        for row in rows:
            _, created = store_repository.upsert(
                StoreWrite(
                    retailer=row.retailer,
                    name=row.name,
                    address=row.address,
                    city=row.city,
                    lat=row.lat,
                    lng=row.lng,
                    timezone=row.timezone,
                    restock_regime=row.restock_regime,
                    active=row.active,
                )
            )
            stores_created += int(created)
            stores_updated += int(not created)

    return SeedSummary(
        stores_created=stores_created,
        stores_updated=stores_updated,
        sources_created=sources_created,
        sources_updated=sources_updated,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed stores and report sources.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help="Store CSV path")
    arguments = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        summary = seed(arguments.csv, session_factory)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        "Seeded "
        f"{summary.stores_total} stores "
        f"({summary.stores_created} created, {summary.stores_updated} updated) and "
        f"{summary.sources_created + summary.sources_updated} sources "
        f"({summary.sources_created} created, {summary.sources_updated} updated)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

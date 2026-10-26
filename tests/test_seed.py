from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.seed_stores import DEFAULT_CSV_PATH, SEED_SOURCES, load_seed_rows, seed
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from restock.db.models import Retailer, Source, Store
from restock.db.session import SessionFactory

pytestmark = pytest.mark.integration

EXAMPLE_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "stores_example.csv"

SWFL_RETAILERS = {
    Retailer.COSTCO,
    Retailer.SAMS_CLUB,
    Retailer.BARNES_NOBLE,
    Retailer.TARGET,
    Retailer.WALMART,
    Retailer.GAMESTOP,
    Retailer.ACE_HARDWARE,
    Retailer.CVS,
    Retailer.WALGREENS,
    Retailer.DOLLAR_GENERAL,
    Retailer.FAMILY_DOLLAR,
}


def test_default_seed_csv_contains_reviewed_swfl_stores() -> None:
    rows = load_seed_rows(DEFAULT_CSV_PATH)

    assert len(rows) == 106
    assert {row.retailer for row in rows} == SWFL_RETAILERS
    assert {row.city for row in rows} == {
        "Bonita Springs",
        "Cape Coral",
        "Estero",
        "Fort Myers",
        "Naples",
        "North Fort Myers",
    }
    assert all(row.timezone == "America/New_York" for row in rows)
    assert all(row.active for row in rows)
    assert all(row.lat is None and row.lng is None for row in rows)
    assert all(not row.name.startswith("EXAMPLE ") for row in rows)


def test_example_seed_csv_contains_six_clearly_fake_rows() -> None:
    rows = load_seed_rows(EXAMPLE_CSV_PATH)

    assert len(rows) == 6
    assert all(row.name.startswith("EXAMPLE ") for row in rows)
    assert all(
        row.address.startswith(
            ("1 Example", "2 Example", "3 Example", "4 Example", "5 Example", "6 Example")
        )
        for row in rows
    )
    assert all(row.timezone == "America/New_York" for row in rows)


def test_seed_is_idempotent(
    session_factory: SessionFactory,
    db_session: Session,
) -> None:
    first = seed(DEFAULT_CSV_PATH, session_factory)
    assert first.stores_created == 106
    assert first.stores_updated == 0
    assert first.sources_created == len(SEED_SOURCES)

    second = seed(DEFAULT_CSV_PATH, session_factory)
    assert second.stores_created == 0
    assert second.stores_updated == 106
    assert second.sources_created == 0
    assert second.sources_updated == len(SEED_SOURCES)

    assert db_session.scalar(select(func.count()).select_from(Store)) == 106
    assert db_session.scalar(select(func.count()).select_from(Source)) == len(SEED_SOURCES)
    source_names = set(db_session.scalars(select(Source.name)))
    assert source_names == {"discord_report", "simulator", "manual_log"}


def test_seed_accepts_new_retailer_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "new-retailers.csv"
    csv_path.write_text(
        "retailer,name,address,city,lat,lng,timezone,restock_regime,active\n"
        "family_dollar,EXAMPLE Family Dollar,10 Example Retail Way,Cape Coral,"
        "26.5629,-81.9495,America/New_York,unknown,true\n"
        "barnes_noble,EXAMPLE Barnes & Noble,11 Example Retail Way,Fort Myers,"
        "26.6406,-81.8723,America/New_York,unknown,true\n"
        "gamestop,EXAMPLE GameStop,12 Example Retail Way,Naples,"
        ",,America/New_York,unknown,true\n",
        encoding="utf-8",
    )

    rows = load_seed_rows(csv_path)

    assert [row.retailer for row in rows] == [
        Retailer.FAMILY_DOLLAR,
        Retailer.BARNES_NOBLE,
        Retailer.GAMESTOP,
    ]


def test_seed_accepts_blank_coordinates(tmp_path: Path) -> None:
    csv_path = tmp_path / "no-coordinates.csv"
    csv_path.write_text(
        "retailer,name,address,city,lat,lng,timezone,restock_regime,active\n"
        "target,EXAMPLE Target,10 Example Retail Way,Cape Coral,"
        " , ,America/New_York,unknown,true\n",
        encoding="utf-8",
    )

    row = load_seed_rows(csv_path)[0]

    assert row.lat is None
    assert row.lng is None


def test_seed_rejects_partial_coordinates(tmp_path: Path) -> None:
    csv_path = tmp_path / "partial-coordinates.csv"
    csv_path.write_text(
        "retailer,name,address,city,lat,lng,timezone,restock_regime,active\n"
        "target,EXAMPLE Target,10 Example Retail Way,Cape Coral,"
        "26.5629,,America/New_York,unknown,true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="both be set or both be blank"):
        load_seed_rows(csv_path)


def test_seed_rejects_duplicate_identity(tmp_path: Path) -> None:
    csv_path = tmp_path / "duplicate.csv"
    original = DEFAULT_CSV_PATH.read_text(encoding="utf-8")
    header, first_row, *_ = original.splitlines()
    csv_path.write_text(f"{header}\n{first_row}\n{first_row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate store identities") as error:
        load_seed_rows(csv_path)
    assert "line 3 duplicates line 2" in str(error.value)

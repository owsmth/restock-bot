from __future__ import annotations

from pathlib import Path

import pytest
from scripts.import_observations_csv import import_csv, main
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from restock.db.models import Observation, ReportOutcome, ReportSource
from restock.db.session import SessionFactory
from restock.repositories.observations import ObservationRepository

pytestmark = pytest.mark.integration

CSV_HEADER = "observed_at_et,retailer,store_hint,event,products,note,source,confidence\n"


def write_csv(path: Path, rows: str) -> Path:
    path.write_text(CSV_HEADER + rows, encoding="utf-8")
    return path


def write_mapping(path: Path, store_id: int) -> Path:
    path.write_text(
        f"store_hint,store_id\nTarget Colonial,{store_id}\n",
        encoding="utf-8",
    )
    return path


def test_import_maps_events_and_skips_rows(
    tmp_path: Path,
    session_factory: SessionFactory,
    seeded_store: int,
    db_session: Session,
) -> None:
    csv_path = write_csv(
        tmp_path / "observations.csv",
        "\n".join(
            [
                "2026-10-26 14:00,Target,Target Colonial,restock,ETB,Two on shelf,facebook,0.8",
                "2026-10-26 14:05,Target,Target Colonial,in_stock,Booster box,Plenty,facebook,0.7",
                "2026-10-26 14:10,Target,Target Colonial,out_of_stock,Tin,,facebook,0.9",
                "2026-10-26 14:15,Target,Target Colonial,none,,Empty shelf,facebook,0.6",
                "2026-10-26 14:20,Target,Target Colonial,schedule_info,,,facebook,0.5",
                ",Target,Target Colonial,in_stock,ETB,,facebook,0.5",
                "",
            ]
        ),
    )
    mapping_path = write_mapping(tmp_path / "mapping.csv", seeded_store)

    dry_run = import_csv(
        session_factory,
        csv_path,
        mapping_path,
        dry_run=True,
    )
    assert dry_run.total_rows == 6
    assert dry_run.importable_rows == 4
    assert dry_run.skipped_schedule_info == 1
    assert dry_run.skipped_blank_date == 1
    assert dry_run.written == 0
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 0

    summary = import_csv(session_factory, csv_path, mapping_path)
    assert summary.written == 4
    assert summary.unmatched_hints == ()
    assert summary.errors == ()

    observations = list(db_session.scalars(select(Observation).order_by(Observation.id)))
    assert [observation.outcome for observation in observations] == [
        ReportOutcome.JUST_DROPPED,
        ReportOutcome.IN_STOCK,
        ReportOutcome.SOLD_OUT,
        ReportOutcome.NOTHING_HERE,
    ]
    assert all(observation.report_source is ReportSource.IMPORTED for observation in observations)
    assert all(observation.reporter_hash is None for observation in observations)
    assert all(observation.source_id != 0 for observation in observations)
    assert observations[0].raw_text is not None
    assert "source='facebook'" in observations[0].raw_text
    assert observations[0].notes == "Two on shelf"
    assert observations[0].in_stock is True
    assert observations[2].in_stock is False

    recent = ObservationRepository(db_session).list_recent(store_id=seeded_store)
    assert recent == []


def test_import_unmatched_hint_writes_nothing(
    tmp_path: Path,
    session_factory: SessionFactory,
    seeded_store: int,
    db_session: Session,
) -> None:
    csv_path = write_csv(
        tmp_path / "observations.csv",
        "2026-10-26 14:00,Target,Unknown Store,in_stock,ETB,,facebook,0.8\n",
    )
    mapping_path = write_mapping(tmp_path / "mapping.csv", seeded_store)

    summary = import_csv(session_factory, csv_path, mapping_path)

    assert summary.written == 0
    assert summary.unmatched_hints == ("Unknown Store",)
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 0


def test_import_cli_exits_nonzero_for_unmatched_hints(
    tmp_path: Path,
    session_factory: SessionFactory,
    seeded_store: int,
    db_session: Session,
) -> None:
    del session_factory
    csv_path = write_csv(
        tmp_path / "observations.csv",
        "2026-10-26 14:00,Target,Unknown Store,in_stock,ETB,,facebook,0.8\n",
    )
    mapping_path = write_mapping(tmp_path / "mapping.csv", seeded_store)

    assert main(["--csv", str(csv_path), "--mapping", str(mapping_path)]) == 1
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 0

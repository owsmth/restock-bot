from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from restock.config import get_settings
from restock.db.engine import create_db_engine
from restock.db.models import ObservationKind, SourceName
from restock.db.session import SessionFactory, create_session_factory, session_scope
from restock.logging import configure_logging
from restock.repositories.observations import ObservationRepository, ObservationWrite
from restock.repositories.sources import SourceRepository
from restock.repositories.stores import StoreRepository
from restock.simulator.generate import (
    SimulationResult,
    SimulationStore,
    simulate,
)
from restock.simulator.patterns import PLANTED_PATTERNS, RestockPattern


def run_simulation(
    session_factory: SessionFactory,
    *,
    weeks: int,
    seed: int,
    end_date: date,
    patterns: Sequence[RestockPattern] = PLANTED_PATTERNS,
) -> SimulationResult:
    starts_on = date.fromordinal(end_date.toordinal() - weeks * 7)
    with session_scope(session_factory) as session:
        stores = StoreRepository(session).list_active()
        source = SourceRepository(session).get_by_name(SourceName.SIMULATOR.value)
        if source is None:
            raise ValueError("Simulator source is missing. Run scripts/seed_stores.py first.")

        simulation_stores = [
            SimulationStore(id=store.id, name=store.name, timezone=store.timezone)
            for store in stores
        ]
        result = simulate(
            stores=simulation_stores,
            starts_on=starts_on,
            weeks=weeks,
            seed=seed,
            patterns=patterns,
        )

        store_ids = {store.name: store.id for store in simulation_stores}
        writes = [
            ObservationWrite(
                kind=ObservationKind.REPORT,
                store_id=store_ids[observation.store_name],
                product_category=observation.product_category,
                in_stock=observation.in_stock,
                observed_at=observation.observed_at,
                reported_at=observation.reported_at,
                source_id=source.id,
                reporter_hash=observation.reporter_hash,
                quantity_estimate=observation.quantity_estimate,
                notes=observation.notes,
            )
            for observation in result.observations
        ]
        ObservationRepository(session).bulk_create(writes)
    return result


def purge_simulator(session_factory: SessionFactory) -> int:
    with session_scope(session_factory) as session:
        source = SourceRepository(session).get_by_name(SourceName.SIMULATOR.value)
        if source is None:
            return 0
        return ObservationRepository(session).delete_by_source(source.id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or purge clearly labeled simulator observations."
    )
    parser.add_argument("--weeks", type=int, default=12, help="Number of weeks to simulate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Exclusive local end date (YYYY-MM-DD); defaults to today",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete only rows whose source is simulator, then exit",
    )
    arguments = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    local_today = datetime.now(ZoneInfo(settings.default_timezone)).date()
    end_date = arguments.end_date or local_today

    try:
        if arguments.purge:
            deleted = purge_simulator(session_factory)
            print(f"Purged {deleted} simulator observations. No other rows were changed.")
            return 0

        result = run_simulation(
            session_factory,
            weeks=arguments.weeks,
            seed=arguments.seed,
            end_date=end_date,
        )
    except (ValueError, SQLAlchemyError) as exc:
        print(f"Simulation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"Generated {len(result.observations)} simulator observations from "
        f"{len(result.restocks)} planted restocks "
        f"({result.starts_on.isoformat()} to {result.ends_on.isoformat()}, "
        f"seed={arguments.seed}). Source=simulator. Purge with --purge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

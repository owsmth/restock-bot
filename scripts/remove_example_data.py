from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from restock.config import get_settings
from restock.db.engine import create_db_engine
from restock.db.models import SourceName
from restock.db.session import SessionFactory, create_session_factory, session_scope
from restock.logging import configure_logging
from restock.repositories.observations import ObservationRepository
from restock.repositories.sources import SourceRepository
from restock.repositories.stores import StoreRepository

EXAMPLE_STORE_PREFIX = "EXAMPLE"


@dataclass(frozen=True, slots=True)
class CleanupSummary:
    stores_before: int
    observations_before: int
    example_stores_targeted: int
    example_observations_targeted: int
    simulator_observations_targeted: int
    example_observations_deleted: int
    simulator_observations_deleted: int
    stores_deleted: int
    stores_after: int
    observations_after: int

    @property
    def observations_deleted(self) -> int:
        return self.example_observations_deleted + self.simulator_observations_deleted


def remove_example_data(session_factory: SessionFactory) -> CleanupSummary:
    with session_scope(session_factory) as session:
        store_repository = StoreRepository(session)
        observation_repository = ObservationRepository(session)
        source_repository = SourceRepository(session)

        stores_before = store_repository.count_all()
        observations_before = observation_repository.count_all()
        example_stores = store_repository.list_by_name_prefix(EXAMPLE_STORE_PREFIX)
        example_store_ids = [store.id for store in example_stores]
        example_observations_targeted = observation_repository.count_by_store_ids(example_store_ids)

        simulator_source = source_repository.get_by_name(SourceName.SIMULATOR.value)
        simulator_observations_targeted = (
            observation_repository.count_by_source(simulator_source.id)
            if simulator_source is not None
            else 0
        )

        # Observations must be removed before their stores.
        simulator_deleted = (
            observation_repository.delete_by_source(simulator_source.id)
            if simulator_source is not None
            else 0
        )
        example_observations_deleted = observation_repository.delete_by_store_ids(example_store_ids)
        stores_deleted = store_repository.delete_ids(example_store_ids)

        stores_after = store_repository.count_all()
        observations_after = observation_repository.count_all()

    return CleanupSummary(
        stores_before=stores_before,
        observations_before=observations_before,
        example_stores_targeted=len(example_stores),
        example_observations_targeted=example_observations_targeted,
        simulator_observations_targeted=simulator_observations_targeted,
        example_observations_deleted=example_observations_deleted,
        simulator_observations_deleted=simulator_deleted,
        stores_deleted=stores_deleted,
        stores_after=stores_after,
        observations_after=observations_after,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete EXAMPLE stores and simulator rows after a preview count."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion. Without this flag nothing is changed.",
    )
    arguments = parser.parse_args(argv)
    if not arguments.yes:
        print(
            "Refusing to delete data without --yes. Re-run with --yes after reviewing the target.",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        summary = remove_example_data(session_factory)
    except SQLAlchemyError as exc:
        print(f"Cleanup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"Before: {summary.stores_before} stores, {summary.observations_before} observations.\n"
        f"Targeted: {summary.example_stores_targeted} EXAMPLE stores, "
        f"{summary.example_observations_targeted} observations at those stores, "
        f"{summary.simulator_observations_targeted} simulator observations.\n"
        f"Deleted: {summary.observations_deleted} observations "
        f"({summary.example_observations_deleted} EXAMPLE-store, "
        f"{summary.simulator_observations_deleted} simulator) and "
        f"{summary.stores_deleted} stores.\n"
        f"After: {summary.stores_after} stores, {summary.observations_after} observations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

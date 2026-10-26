from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from restock.config import get_settings
from restock.db.engine import create_db_engine
from restock.db.models import Retailer
from restock.db.session import SessionFactory, create_session_factory
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository, StoreWrite

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)
TEST_DATABASE_URL = os.environ.get(
    "RESTOCK_TEST_DATABASE_URL",
    "postgresql+psycopg://restock:restock@localhost:5432/restock_test",
)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.setdefault("REPORTER_HASH_SALT", "test-salt-at-least-sixteen-characters")
    get_settings.cache_clear()

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def session_factory(db_engine: Engine) -> SessionFactory:
    return create_session_factory(db_engine)


@pytest.fixture(autouse=True)
def clean_database(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE observations, predictions, sources, stores RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def db_session(session_factory: SessionFactory) -> Iterator[Session]:
    with session_factory() as session:
        yield session
        session.rollback()


@pytest.fixture
def seeded_source(db_session: Session) -> int:
    source, _ = SourceRepository(db_session).upsert(
        SourceWrite(
            name="discord_report",
            trust_weight=0.65,
            compliance_note="Test source",
        )
    )
    db_session.commit()
    return source.id


@pytest.fixture
def seeded_store(db_session: Session) -> int:
    store, _ = StoreRepository(db_session).upsert(
        StoreWrite(
            retailer=Retailer.TARGET,
            name="EXAMPLE Test Store",
            address="1 Example Retail Way",
            city="Cape Coral",
            lat=26.5629,
            lng=-81.9495,
            timezone="America/New_York",
        )
    )
    db_session.commit()
    return store.id

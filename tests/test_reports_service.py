from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from restock.db.models import (
    Observation,
    ProductCategory,
    RestockRegime,
    Retailer,
    SourceName,
)
from restock.db.session import SessionFactory, session_scope
from restock.repositories.sources import SourceRepository, SourceWrite
from restock.repositories.stores import StoreRepository, StoreWrite
from restock.services.errors import (
    DuplicateReportError,
    InvalidReportError,
    RateLimitExceededError,
    ReportingUnavailableError,
    ReportNotFoundError,
    StoreInactiveError,
    StoreNotFoundError,
)
from restock.services.reports import ReportService, hash_reporter_id

pytestmark = pytest.mark.integration

FIXED_NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
SALT = "test-salt-at-least-sixteen-characters"


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(FIXED_NOW)


@pytest.fixture
def report_service(
    session_factory: SessionFactory,
    seeded_source: int,
    clock: MutableClock,
) -> ReportService:
    del seeded_source
    return ReportService(
        session_factory,
        reporter_hash_salt=SALT,
        clock=clock,
    )


def test_hash_reporter_id_is_stable_salted_and_not_raw() -> None:
    first = hash_reporter_id(123456789, SALT)
    second = hash_reporter_id(123456789, SALT)
    other_user = hash_reporter_id(987654321, SALT)
    other_salt = hash_reporter_id(123456789, f"{SALT}-different")

    assert first == second
    assert first != other_user
    assert first != other_salt
    assert len(first) == 64
    assert "123456789" not in first


def test_submit_report_stores_utc_and_hashed_reporter(
    report_service: ReportService,
    seeded_store: int,
    db_session: Session,
) -> None:
    receipt = report_service.submit_report(
        reporter_id=123456789,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
        minutes_ago=12,
        note="  Top shelf, two left  ",
    )

    observation = db_session.scalar(select(Observation))
    assert observation is not None
    assert receipt.store_timezone == "America/New_York"
    assert receipt.store_city == "Cape Coral"
    assert observation.store_id == seeded_store
    assert observation.kind.value == "report"
    assert observation.product_category is ProductCategory.ETB
    assert observation.in_stock is True
    assert observation.observed_at == FIXED_NOW - timedelta(minutes=12)
    assert observation.reported_at == FIXED_NOW
    assert observation.observed_at.tzinfo is not None
    assert observation.reported_at.tzinfo is not None
    assert observation.reporter_hash == hash_reporter_id(123456789, SALT)
    assert observation.notes == "Top shelf, two left"
    assert "123456789" not in (observation.reporter_hash or "")


def test_duplicate_within_thirty_minutes_is_rejected(
    report_service: ReportService,
    seeded_store: int,
    clock: MutableClock,
) -> None:
    report_service.submit_report(
        reporter_id=123456789,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    with pytest.raises(DuplicateReportError):
        report_service.submit_report(
            reporter_id=123456789,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            in_stock=True,
        )

    clock.now += timedelta(minutes=30, seconds=1)
    receipt = report_service.submit_report(
        reporter_id=123456789,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    assert receipt.observation_id > 0


def test_duplicate_key_includes_in_stock_and_reporter(
    report_service: ReportService,
    seeded_store: int,
) -> None:
    first = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    other_stock = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=False,
    )
    other_reporter = report_service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )

    assert (
        len({first.observation_id, other_stock.observation_id, other_reporter.observation_id}) == 3
    )


def test_rate_limit_is_per_reporter_and_configurable(
    session_factory: SessionFactory,
    seeded_source: int,
    seeded_store: int,
    clock: MutableClock,
) -> None:
    del seeded_source
    service = ReportService(
        session_factory,
        reporter_hash_salt=SALT,
        clock=clock,
        rate_limit_per_hour=2,
    )
    service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    clock.now += timedelta(minutes=1)
    service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.BOOSTER_BOX,
        in_stock=False,
    )

    clock.now += timedelta(minutes=1)
    with pytest.raises(RateLimitExceededError, match="2 reports per hour"):
        service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.TIN,
            in_stock=True,
        )

    service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )

    clock.now += timedelta(hours=1, seconds=1)
    receipt = service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    assert receipt.observation_id > 0


def test_admin_delete_report(
    report_service: ReportService,
    seeded_store: int,
    db_session: Session,
) -> None:
    receipt = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )

    deleted = report_service.delete_report(receipt.observation_id)

    assert deleted.observation_id == receipt.observation_id
    assert deleted.store_id == seeded_store
    assert deleted.store_name == "EXAMPLE Test Store"
    assert deleted.product_category is ProductCategory.ETB
    assert deleted.in_stock is True
    db_session.expire_all()
    assert db_session.get(Observation, receipt.observation_id) is None
    with pytest.raises(ReportNotFoundError):
        report_service.delete_report(receipt.observation_id)


@pytest.mark.parametrize(
    ("minutes_ago", "note", "message"),
    [
        (-1, None, "minutes_ago"),
        (2_881, None, "minutes_ago"),
        (0, "x" * 281, "note"),
    ],
)
def test_invalid_report_is_rejected(
    report_service: ReportService,
    seeded_store: int,
    minutes_ago: int,
    note: str | None,
    message: str,
) -> None:
    with pytest.raises(InvalidReportError, match=message):
        report_service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            in_stock=True,
            minutes_ago=minutes_ago,
            note=note,
        )


def test_report_accepts_exactly_forty_eight_hours_ago(
    report_service: ReportService,
    seeded_store: int,
) -> None:
    receipt = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
        minutes_ago=2_880,
    )
    assert receipt.observed_at == FIXED_NOW - timedelta(hours=48)


def test_missing_store_is_rejected(report_service: ReportService) -> None:
    with pytest.raises(StoreNotFoundError):
        report_service.submit_report(
            reporter_id=1,
            store_id=999_999,
            product_category=ProductCategory.ETB,
            in_stock=True,
        )


def test_inactive_store_is_rejected(
    session_factory: SessionFactory,
    clock: MutableClock,
) -> None:
    with session_scope(session_factory) as session:
        SourceRepository(session).upsert(
            SourceWrite(
                name=SourceName.DISCORD_REPORT.value,
                trust_weight=0.65,
                compliance_note="Test",
            )
        )
        store, _ = StoreRepository(session).upsert(
            StoreWrite(
                retailer=Retailer.TARGET,
                name="EXAMPLE Inactive Store",
                address="1 Example Retail Way",
                city="Cape Coral",
                lat=26.5,
                lng=-81.9,
                timezone="America/New_York",
                restock_regime=RestockRegime.UNKNOWN,
                active=False,
            )
        )
        store_id = store.id

    service = ReportService(session_factory, reporter_hash_salt=SALT, clock=clock)
    with pytest.raises(StoreInactiveError):
        service.submit_report(
            reporter_id=1,
            store_id=store_id,
            product_category=ProductCategory.ETB,
            in_stock=True,
        )


def test_missing_source_is_rejected(
    session_factory: SessionFactory,
    seeded_store: int,
    clock: MutableClock,
) -> None:
    service = ReportService(session_factory, reporter_hash_salt=SALT, clock=clock)
    with pytest.raises(ReportingUnavailableError):
        service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            in_stock=True,
        )


def test_list_recent_orders_filters_and_includes_source(
    report_service: ReportService,
    seeded_store: int,
    clock: MutableClock,
) -> None:
    report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        in_stock=True,
    )
    clock.now += timedelta(minutes=5)
    report_service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.BOOSTER_BOX,
        in_stock=False,
        note="Sold out",
    )

    recent = report_service.list_recent(store_id=seeded_store)
    assert recent.store_timezone == "America/New_York"
    assert [item.product_category for item in recent.reports] == [
        ProductCategory.BOOSTER_BOX,
        ProductCategory.ETB,
    ]
    assert recent.reports[0].notes == "Sold out"
    assert all(item.source_name == "discord_report" for item in recent.reports)

    filtered = report_service.list_recent(
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
    )
    assert len(filtered.reports) == 1
    assert filtered.reports[0].product_category is ProductCategory.ETB


def test_list_recent_returns_at_most_ten(
    report_service: ReportService,
    seeded_store: int,
    clock: MutableClock,
) -> None:
    for index in range(12):
        clock.now += timedelta(minutes=31)
        report_service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            in_stock=index % 2 == 0,
        )

    recent = report_service.list_recent(store_id=seeded_store)
    assert len(recent.reports) == 10


def test_list_recent_rejects_missing_store(report_service: ReportService) -> None:
    with pytest.raises(StoreNotFoundError):
        report_service.list_recent(store_id=999_999)

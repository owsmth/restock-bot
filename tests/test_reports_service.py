from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from restock.db.models import (
    Observation,
    ObservationKind,
    ProductCategory,
    ReportOutcome,
    ReportSource,
    RestockRegime,
    Retailer,
    SourceName,
)
from restock.db.session import SessionFactory, session_scope
from restock.repositories.observations import ObservationRepository, ObservationWrite
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
        outcome=ReportOutcome.IN_STOCK,
        quantity_note="  two left  ",
        raw_text="  Top shelf  ",
        report_source=ReportSource.DROPDOWN,
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
    assert observation.outcome is ReportOutcome.IN_STOCK
    assert observation.in_stock is True
    assert observation.quantity_note == "two left"
    assert observation.raw_text == "Top shelf"
    assert observation.report_source is ReportSource.DROPDOWN
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
        outcome=ReportOutcome.IN_STOCK,
    )
    with pytest.raises(DuplicateReportError):
        report_service.submit_report(
            reporter_id=123456789,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            outcome=ReportOutcome.IN_STOCK,
        )

    clock.now += timedelta(minutes=30, seconds=1)
    receipt = report_service.submit_report(
        reporter_id=123456789,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
    )
    assert receipt.observation_id > 0


def test_duplicate_key_includes_outcome_and_reporter(
    report_service: ReportService,
    seeded_store: int,
) -> None:
    first = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
    )
    other_stock = report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.SOLD_OUT,
    )
    other_reporter = report_service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
    )

    assert (
        len({first.observation_id, other_stock.observation_id, other_reporter.observation_id}) == 3
    )


def test_duplicate_key_ignores_product(
    report_service: ReportService,
    seeded_store: int,
) -> None:
    report_service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
    )

    with pytest.raises(DuplicateReportError):
        report_service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.BOOSTER_BOX,
            outcome=ReportOutcome.IN_STOCK,
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
        outcome=ReportOutcome.IN_STOCK,
    )
    clock.now += timedelta(minutes=1)
    service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.BOOSTER_BOX,
        outcome=ReportOutcome.SOLD_OUT,
    )

    clock.now += timedelta(minutes=1)
    with pytest.raises(RateLimitExceededError, match="2 reports per hour"):
        service.submit_report(
            reporter_id=1,
            store_id=seeded_store,
            product_category=ProductCategory.TIN,
            outcome=ReportOutcome.IN_STOCK,
        )

    service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
    )

    clock.now += timedelta(hours=1, seconds=1)
    receipt = service.submit_report(
        reporter_id=1,
        store_id=seeded_store,
        product_category=ProductCategory.ETB,
        outcome=ReportOutcome.IN_STOCK,
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
        outcome=ReportOutcome.IN_STOCK,
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
            outcome=ReportOutcome.IN_STOCK,
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
        outcome=ReportOutcome.IN_STOCK,
        minutes_ago=2_880,
    )
    assert receipt.observed_at == FIXED_NOW - timedelta(hours=48)


def test_missing_store_is_rejected(report_service: ReportService) -> None:
    with pytest.raises(StoreNotFoundError):
        report_service.submit_report(
            reporter_id=1,
            store_id=999_999,
            product_category=ProductCategory.ETB,
            outcome=ReportOutcome.IN_STOCK,
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
            outcome=ReportOutcome.IN_STOCK,
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
            outcome=ReportOutcome.IN_STOCK,
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
        outcome=ReportOutcome.IN_STOCK,
    )
    clock.now += timedelta(minutes=5)
    report_service.submit_report(
        reporter_id=2,
        store_id=seeded_store,
        product_category=ProductCategory.BOOSTER_BOX,
        outcome=ReportOutcome.SOLD_OUT,
        note="Sold out",
    )

    recent = report_service.list_recent(store_id=seeded_store)
    assert recent.store_timezone == "America/New_York"
    assert [item.product_category for item in recent.reports] == [
        ProductCategory.BOOSTER_BOX,
        ProductCategory.ETB,
    ]
    assert recent.reports[0].notes == "Sold out"
    assert recent.reports[0].outcome is ReportOutcome.SOLD_OUT
    assert recent.reports[1].outcome is ReportOutcome.IN_STOCK
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
            outcome=(ReportOutcome.IN_STOCK if index % 2 == 0 else ReportOutcome.SOLD_OUT),
        )

    recent = report_service.list_recent(store_id=seeded_store)
    assert len(recent.reports) == 10


def test_list_recent_excludes_imported_rows(
    report_service: ReportService,
    seeded_store: int,
    seeded_source: int,
    db_session: Session,
) -> None:
    ObservationRepository(db_session).create(
        ObservationWrite(
            kind=ObservationKind.REPORT,
            store_id=seeded_store,
            product_category=ProductCategory.ETB,
            in_stock=True,
            outcome=ReportOutcome.IN_STOCK,
            observed_at=FIXED_NOW,
            reported_at=FIXED_NOW,
            source_id=seeded_source,
            reporter_hash=None,
            report_source=ReportSource.IMPORTED,
        )
    )
    db_session.commit()

    recent = report_service.list_recent(store_id=seeded_store)
    assert recent.reports == ()


def test_time_to_sold_out_uses_local_day_and_store(
    report_service: ReportService,
    seeded_store: int,
    seeded_source: int,
    db_session: Session,
) -> None:
    repository = ObservationRepository(db_session)
    drop_at = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    sale_at = datetime(2026, 10, 26, 18, 25, tzinfo=UTC)
    for outcome, observed_at in (
        (ReportOutcome.JUST_DROPPED, drop_at),
        (ReportOutcome.SOLD_OUT, sale_at),
    ):
        repository.create(
            ObservationWrite(
                kind=ObservationKind.REPORT,
                store_id=seeded_store,
                product_category=ProductCategory.ETB,
                in_stock=outcome is ReportOutcome.JUST_DROPPED,
                outcome=outcome,
                observed_at=observed_at,
                reported_at=observed_at,
                source_id=seeded_source,
                reporter_hash=None,
            )
        )
    db_session.commit()

    assert report_service.time_to_sold_out(
        seeded_store,
        date(2026, 10, 26),
    ) == timedelta(minutes=25)


def test_list_recent_rejects_missing_store(report_service: ReportService) -> None:
    with pytest.raises(StoreNotFoundError):
        report_service.list_recent(store_id=999_999)

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from restock.db.models import ObservationKind, ProductCategory, SourceName
from restock.db.session import SessionFactory, session_scope
from restock.repositories.observations import ObservationRepository, ObservationWrite
from restock.repositories.sources import SourceRepository
from restock.repositories.stores import StoreRepository
from restock.services.errors import (
    DuplicateReportError,
    InvalidReportError,
    ReportingUnavailableError,
    StoreInactiveError,
    StoreNotFoundError,
)

logger = structlog.get_logger(__name__)

MAX_MINUTES_AGO = 2_880
MAX_NOTE_LENGTH = 280
DUPLICATE_WINDOW = timedelta(minutes=30)
RECENT_LIMIT = 10

NoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOTE_LENGTH),
]


class ReportSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: int = Field(gt=0)
    product_category: ProductCategory
    in_stock: bool
    minutes_ago: int = Field(default=0, ge=0, le=MAX_MINUTES_AGO)
    note: NoteText | None = None

    @field_validator("note")
    @classmethod
    def empty_note_is_none(cls, value: str | None) -> str | None:
        return value or None


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    observation_id: int
    store_name: str
    store_timezone: str
    product_category: ProductCategory
    in_stock: bool
    observed_at: datetime
    reported_at: datetime


@dataclass(frozen=True, slots=True)
class RecentReport:
    observation_id: int
    product_category: ProductCategory
    in_stock: bool
    observed_at: datetime
    reported_at: datetime
    source_name: str
    notes: str | None


@dataclass(frozen=True, slots=True)
class RecentReports:
    store_id: int
    store_name: str
    store_timezone: str
    reports: tuple[RecentReport, ...]


def hash_reporter_id(discord_user_id: int, salt: str) -> str:
    if discord_user_id <= 0:
        raise ValueError("discord_user_id must be positive")
    return hashlib.sha256(f"{salt}:{discord_user_id}".encode()).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def _validation_message(error: ValidationError) -> str:
    details = error.errors()
    if not details:
        return "Invalid report."
    first = details[0]
    field = ".".join(str(part) for part in first["loc"])
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"Invalid report: {field}: {message}."


class ReportService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        reporter_hash_salt: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._reporter_hash_salt = reporter_hash_salt
        self._clock = clock

    def submit_report(
        self,
        *,
        reporter_id: int,
        store_id: int,
        product_category: ProductCategory | str,
        in_stock: bool,
        minutes_ago: int = 0,
        note: str | None = None,
    ) -> ReportReceipt:
        try:
            submission = ReportSubmission(
                store_id=store_id,
                product_category=product_category,
                in_stock=in_stock,
                minutes_ago=minutes_ago,
                note=note,
            )
            reporter_hash = hash_reporter_id(reporter_id, self._reporter_hash_salt)
        except (ValidationError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise InvalidReportError(_validation_message(exc)) from exc
            raise InvalidReportError("Invalid report: reporter identity was rejected.") from exc

        reported_at = self._clock()
        if reported_at.tzinfo is None:
            raise RuntimeError("ReportService clock must return a timezone-aware datetime")
        reported_at = reported_at.astimezone(UTC)
        observed_at = reported_at - timedelta(minutes=submission.minutes_ago)

        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).get(submission.store_id)
            if store is None:
                raise StoreNotFoundError(submission.store_id)
            if not store.active:
                raise StoreInactiveError(store.name)

            source = SourceRepository(session).get_by_name(SourceName.DISCORD_REPORT.value)
            if source is None:
                raise ReportingUnavailableError()

            observation_repository = ObservationRepository(session)
            if observation_repository.has_recent_duplicate(
                reporter_hash=reporter_hash,
                store_id=store.id,
                product_category=submission.product_category,
                in_stock=submission.in_stock,
                submitted_since=reported_at - DUPLICATE_WINDOW,
            ):
                raise DuplicateReportError()

            observation = observation_repository.create(
                ObservationWrite(
                    kind=ObservationKind.REPORT,
                    store_id=store.id,
                    product_category=submission.product_category,
                    in_stock=submission.in_stock,
                    observed_at=observed_at,
                    reported_at=reported_at,
                    source_id=source.id,
                    reporter_hash=reporter_hash,
                    notes=submission.note,
                )
            )
            receipt = ReportReceipt(
                observation_id=observation.id,
                store_name=store.name,
                store_timezone=store.timezone,
                product_category=observation.product_category,
                in_stock=observation.in_stock,
                observed_at=observation.observed_at,
                reported_at=observation.reported_at,
            )

        logger.info(
            "report_created",
            observation_id=receipt.observation_id,
            store_id=submission.store_id,
            product_category=submission.product_category.value,
            in_stock=submission.in_stock,
            minutes_ago=submission.minutes_ago,
        )
        return receipt

    def list_recent(
        self,
        *,
        store_id: int,
        product_category: ProductCategory | str | None = None,
        limit: int = RECENT_LIMIT,
    ) -> RecentReports:
        if store_id <= 0:
            raise StoreNotFoundError(store_id)
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")

        category: ProductCategory | None = None
        if product_category is not None:
            try:
                category = ProductCategory(product_category)
            except ValueError as exc:
                raise InvalidReportError(
                    "Invalid product category. Choose one from the command options."
                ) from exc

        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).get(store_id)
            if store is None:
                raise StoreNotFoundError(store_id)
            if not store.active:
                raise StoreInactiveError(store.name)

            records = ObservationRepository(session).list_recent(
                store_id=store.id,
                product_category=category,
                limit=limit,
            )
            reports = tuple(
                RecentReport(
                    observation_id=record.observation.id,
                    product_category=record.observation.product_category,
                    in_stock=record.observation.in_stock,
                    observed_at=record.observation.observed_at,
                    reported_at=record.observation.reported_at,
                    source_name=record.source_name,
                    notes=record.observation.notes,
                )
                for record in records
            )
            return RecentReports(
                store_id=store.id,
                store_name=store.name,
                store_timezone=store.timezone,
                reports=reports,
            )

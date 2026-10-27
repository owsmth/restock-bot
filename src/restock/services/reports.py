from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import structlog
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from restock.db.models import (
    ObservationKind,
    ProductCategory,
    ReportOutcome,
    ReportSource,
    SourceName,
)
from restock.db.session import SessionFactory, session_scope
from restock.repositories.observations import (
    ObservationRepository,
    ObservationWrite,
    OutcomeObservation,
)
from restock.repositories.sources import SourceRepository
from restock.repositories.stores import StoreRepository
from restock.services.errors import (
    DuplicateReportError,
    InvalidReportError,
    RateLimitExceededError,
    ReportingUnavailableError,
    ReportNotFoundError,
    StoreInactiveError,
    StoreNotFoundError,
)

logger = structlog.get_logger(__name__)

MAX_MINUTES_AGO = 2_880
MAX_NOTE_LENGTH = 280
MAX_QUANTITY_NOTE_LENGTH = 200
MAX_RAW_TEXT_LENGTH = 2_000
DUPLICATE_WINDOW = timedelta(minutes=30)
RECENT_LIMIT = 10
SOLD_OUT_TIMEZONE = "America/New_York"

NoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOTE_LENGTH),
]
QuantityText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_QUANTITY_NOTE_LENGTH,
    ),
]
RawText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_RAW_TEXT_LENGTH),
]


class ReportSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: int = Field(gt=0)
    outcome: ReportOutcome
    product_category: ProductCategory = ProductCategory.OTHER
    quantity_note: QuantityText | None = None
    raw_text: RawText | None = None
    report_source: ReportSource = ReportSource.DROPDOWN
    minutes_ago: int = Field(default=0, ge=0, le=MAX_MINUTES_AGO)
    note: NoteText | None = None

    @field_validator("quantity_note", "raw_text", "note")
    @classmethod
    def empty_text_is_none(cls, value: str | None) -> str | None:
        return value or None


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    observation_id: int
    store_name: str
    store_city: str
    store_timezone: str
    product_category: ProductCategory
    outcome: ReportOutcome
    observed_at: datetime
    reported_at: datetime
    quantity_note: str | None = None
    raw_text: str | None = None
    report_source: ReportSource = ReportSource.DROPDOWN

    @property
    def in_stock(self) -> bool:
        return outcome_in_stock(self.outcome)


@dataclass(frozen=True, slots=True)
class DeletedReport:
    observation_id: int
    store_id: int
    store_name: str
    product_category: ProductCategory
    in_stock: bool
    outcome: ReportOutcome | None = None
    report_source: ReportSource = ReportSource.DROPDOWN


@dataclass(frozen=True, slots=True)
class RecentReport:
    observation_id: int
    product_category: ProductCategory
    in_stock: bool
    observed_at: datetime
    reported_at: datetime
    source_name: str
    notes: str | None
    outcome: ReportOutcome | None = None
    quantity_note: str | None = None
    raw_text: str | None = None
    report_source: ReportSource = ReportSource.DROPDOWN


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


def outcome_in_stock(outcome: ReportOutcome) -> bool:
    return outcome in (ReportOutcome.JUST_DROPPED, ReportOutcome.IN_STOCK)


def time_to_sold_out(
    rows: Sequence[OutcomeObservation],
    store_id: int,
    local_day: date,
    timezone_name: str = SOLD_OUT_TIMEZONE,
) -> timedelta | None:
    timezone = ZoneInfo(timezone_name)
    store_rows = [
        row
        for row in rows
        if row.store_id == store_id and row.observed_at.astimezone(timezone).date() == local_day
    ]
    drops = [row.observed_at for row in store_rows if row.outcome is ReportOutcome.JUST_DROPPED]
    if not drops:
        return None

    earliest_drop = min(drops)
    sold_outs = [
        row.observed_at
        for row in store_rows
        if row.outcome is ReportOutcome.SOLD_OUT and row.observed_at > earliest_drop
    ]
    if not sold_outs:
        return None
    return min(sold_outs) - earliest_drop


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
        rate_limit_per_hour: int = 10,
    ) -> None:
        if rate_limit_per_hour < 1:
            raise ValueError("rate_limit_per_hour must be positive")
        self._session_factory = session_factory
        self._reporter_hash_salt = reporter_hash_salt
        self._clock = clock
        self._rate_limit_per_hour = rate_limit_per_hour

    def submit_report(
        self,
        *,
        reporter_id: int,
        store_id: int,
        outcome: ReportOutcome | str,
        product_category: ProductCategory | str = ProductCategory.OTHER,
        quantity_note: str | None = None,
        raw_text: str | None = None,
        report_source: ReportSource | str = ReportSource.DROPDOWN,
        minutes_ago: int = 0,
        note: str | None = None,
    ) -> ReportReceipt:
        try:
            submission = ReportSubmission(
                store_id=store_id,
                outcome=outcome,
                product_category=product_category,
                quantity_note=quantity_note,
                raw_text=raw_text,
                report_source=report_source,
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
        in_stock = outcome_in_stock(submission.outcome)

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
            observation_repository.lock_reporter(reporter_hash)
            recent_reports = observation_repository.count_recent_by_reporter(
                reporter_hash=reporter_hash,
                submitted_since=reported_at - timedelta(hours=1),
                source_id=source.id,
            )
            if recent_reports >= self._rate_limit_per_hour:
                logger.info(
                    "report_rate_limited",
                    store_id=submission.store_id,
                    rate_limit_per_hour=self._rate_limit_per_hour,
                )
                raise RateLimitExceededError(self._rate_limit_per_hour)

            observation_repository.lock_report_identity(
                reporter_hash=reporter_hash,
                store_id=store.id,
                outcome=submission.outcome,
            )
            if observation_repository.has_recent_duplicate(
                reporter_hash=reporter_hash,
                store_id=store.id,
                outcome=submission.outcome,
                submitted_since=reported_at - DUPLICATE_WINDOW,
            ):
                raise DuplicateReportError()

            observation = observation_repository.create(
                ObservationWrite(
                    kind=ObservationKind.REPORT,
                    store_id=store.id,
                    product_category=submission.product_category,
                    in_stock=in_stock,
                    outcome=submission.outcome,
                    observed_at=observed_at,
                    reported_at=reported_at,
                    source_id=source.id,
                    reporter_hash=reporter_hash,
                    quantity_note=submission.quantity_note,
                    raw_text=submission.raw_text,
                    notes=submission.note,
                    report_source=submission.report_source,
                )
            )
            receipt = ReportReceipt(
                observation_id=observation.id,
                store_name=store.name,
                store_city=store.city,
                store_timezone=store.timezone,
                product_category=observation.product_category,
                outcome=submission.outcome,
                observed_at=observation.observed_at,
                reported_at=observation.reported_at,
                quantity_note=observation.quantity_note,
                raw_text=observation.raw_text,
                report_source=observation.report_source,
            )

        logger.info(
            "report_created",
            observation_id=receipt.observation_id,
            store_id=submission.store_id,
            product_category=submission.product_category.value,
            outcome=submission.outcome.value,
            report_source=submission.report_source.value,
            minutes_ago=submission.minutes_ago,
            has_raw_text=submission.raw_text is not None,
        )
        return receipt

    def delete_report(self, observation_id: int) -> DeletedReport:
        if observation_id <= 0:
            raise ReportNotFoundError(observation_id)

        with session_scope(self._session_factory) as session:
            observation_repository = ObservationRepository(session)
            observation = observation_repository.get(observation_id)
            if observation is None:
                raise ReportNotFoundError(observation_id)
            store = StoreRepository(session).get(observation.store_id)
            deleted = observation_repository.delete_by_id(observation.id)
            if not deleted:
                raise ReportNotFoundError(observation_id)
            deleted_report = DeletedReport(
                observation_id=observation.id,
                store_id=observation.store_id,
                store_name=store.name if store is not None else f"store {observation.store_id}",
                product_category=observation.product_category,
                in_stock=observation.in_stock,
                outcome=observation.outcome,
                report_source=observation.report_source,
            )

        logger.info(
            "report_deleted",
            observation_id=deleted_report.observation_id,
            store_id=deleted_report.store_id,
        )
        return deleted_report

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
                    outcome=record.observation.outcome,
                    observed_at=record.observation.observed_at,
                    reported_at=record.observation.reported_at,
                    source_name=record.source_name,
                    notes=record.observation.notes,
                    quantity_note=record.observation.quantity_note,
                    raw_text=record.observation.raw_text,
                    report_source=record.observation.report_source,
                )
                for record in records
            )
            return RecentReports(
                store_id=store.id,
                store_name=store.name,
                store_timezone=store.timezone,
                reports=reports,
            )

    def time_to_sold_out(self, store_id: int, local_day: date) -> timedelta | None:
        if store_id <= 0:
            raise StoreNotFoundError(store_id)

        timezone = ZoneInfo(SOLD_OUT_TIMEZONE)
        day_start = datetime.combine(local_day, time.min, tzinfo=timezone)
        day_end = day_start + timedelta(days=1)
        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).get(store_id)
            if store is None:
                raise StoreNotFoundError(store_id)
            rows = ObservationRepository(session).list_outcomes(
                store_id=store_id,
                start=day_start.astimezone(UTC),
                end=day_end.astimezone(UTC),
            )
        return time_to_sold_out(rows, store_id, local_day)

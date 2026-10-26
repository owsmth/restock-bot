from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Retailer(StrEnum):
    TARGET = "target"
    WALMART = "walmart"
    SAMS_CLUB = "sams_club"
    COSTCO = "costco"
    BEST_BUY = "best_buy"
    DOLLAR_GENERAL = "dollar_general"
    WALGREENS = "walgreens"
    CVS = "cvs"
    ACE_HARDWARE = "ace_hardware"
    OTHER = "other"


class RestockRegime(StrEnum):
    SCHEDULED = "scheduled"
    RANDOM = "random"
    SNAPSHOT = "snapshot"
    UNKNOWN = "unknown"


class ObservationKind(StrEnum):
    REPORT = "report"
    SNAPSHOT = "snapshot"


class ProductCategory(StrEnum):
    BOOSTER_BOX = "booster_box"
    ETB = "etb"
    BOOSTER_BUNDLE = "booster_bundle"
    BLISTER = "blister"
    TIN = "tin"
    COLLECTION_BOX = "collection_box"
    OTHER = "other"


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


retailer_enum = Enum(Retailer, name="retailer", values_callable=_enum_values)
restock_regime_enum = Enum(
    RestockRegime,
    name="restock_regime",
    values_callable=_enum_values,
)
observation_kind_enum = Enum(
    ObservationKind,
    name="observation_kind",
    values_callable=_enum_values,
)
product_category_enum = Enum(
    ProductCategory,
    name="product_category",
    values_callable=_enum_values,
)


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("retailer", "name", "address", name="uq_stores_identity"),
        CheckConstraint("lat BETWEEN -90 AND 90", name="ck_stores_lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="ck_stores_lng_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    retailer: Mapped[Retailer] = mapped_column(retailer_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="America/New_York",
        server_default="America/New_York",
    )
    restock_regime: Mapped[RestockRegime] = mapped_column(
        restock_regime_enum,
        nullable=False,
        default=RestockRegime.UNKNOWN,
        server_default=RestockRegime.UNKNOWN.value,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("trust_weight >= 0", name="ck_sources_trust_weight_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    trust_weight: Mapped[float] = mapped_column(Float, nullable=False)
    compliance_note: Mapped[str] = mapped_column(Text, nullable=False)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("observed_at <= reported_at", name="ck_observations_time_order"),
        CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 280",
            name="ck_observations_notes_length",
        ),
        CheckConstraint(
            "reporter_hash IS NULL OR char_length(reporter_hash) = 64",
            name="ck_observations_reporter_hash_length",
        ),
        Index(
            "ix_observations_store_category_observed_at",
            "store_id",
            "product_category",
            "observed_at",
        ),
        Index(
            "ix_observations_dedup",
            "reporter_hash",
            "store_id",
            "product_category",
            "in_stock",
            "reported_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[ObservationKind] = mapped_column(
        observation_kind_enum,
        nullable=False,
        default=ObservationKind.REPORT,
        server_default=ObservationKind.REPORT.value,
    )
    store_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("stores.id", name="fk_observations_store_id"),
        nullable=False,
    )
    product_category: Mapped[ProductCategory] = mapped_column(
        product_category_enum,
        nullable=False,
    )
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sources.id", name="fk_observations_source_id"),
        nullable=False,
    )
    reporter_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(280), nullable=True)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("window_end > window_start", name="ck_predictions_window_order"),
        CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="ck_predictions_probability_range",
        ),
        CheckConstraint("n_observations >= 0", name="ck_predictions_n_observations"),
    )

    store_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("stores.id", name="fk_predictions_store_id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_category: Mapped[ProductCategory] = mapped_column(
        product_category_enum,
        primary_key=True,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

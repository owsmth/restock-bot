"""Initial schema for restock reports.

Revision ID: 0001
Revises:
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

retailer = postgresql.ENUM(
    "target",
    "walmart",
    "sams_club",
    "costco",
    "best_buy",
    "dollar_general",
    "walgreens",
    "cvs",
    "ace_hardware",
    "other",
    name="retailer",
    create_type=False,
)
restock_regime = postgresql.ENUM(
    "scheduled",
    "random",
    "snapshot",
    "unknown",
    name="restock_regime",
    create_type=False,
)
observation_kind = postgresql.ENUM(
    "report",
    "snapshot",
    name="observation_kind",
    create_type=False,
)
product_category = postgresql.ENUM(
    "booster_box",
    "etb",
    "booster_bundle",
    "blister",
    "tin",
    "collection_box",
    "other",
    name="product_category",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    retailer.create(bind, checkfirst=True)
    restock_regime.create(bind, checkfirst=True)
    observation_kind.create(bind, checkfirst=True)
    product_category.create(bind, checkfirst=True)

    op.create_table(
        "stores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("retailer", retailer, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="America/New_York",
            nullable=False,
        ),
        sa.Column(
            "restock_regime",
            restock_regime,
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="ck_stores_lat_range"),
        sa.CheckConstraint("lng BETWEEN -180 AND 180", name="ck_stores_lng_range"),
        sa.UniqueConstraint("retailer", "name", "address", name="uq_stores_identity"),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("trust_weight", sa.Float(), nullable=False),
        sa.Column("compliance_note", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "trust_weight >= 0",
            name="ck_sources_trust_weight_nonnegative",
        ),
        sa.UniqueConstraint("name", name="uq_sources_name"),
    )

    op.create_table(
        "observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "kind",
            observation_kind,
            server_default="report",
            nullable=False,
        ),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("product_category", product_category, nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_hash", sa.String(length=64), nullable=True),
        sa.Column("quantity_estimate", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=280), nullable=True),
        sa.CheckConstraint(
            "observed_at <= reported_at",
            name="ck_observations_time_order",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 280",
            name="ck_observations_notes_length",
        ),
        sa.CheckConstraint(
            "reporter_hash IS NULL OR char_length(reporter_hash) = 64",
            name="ck_observations_reporter_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_observations_store_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_observations_source_id",
        ),
    )
    op.create_index(
        "ix_observations_store_category_observed_at",
        "observations",
        ["store_id", "product_category", "observed_at"],
    )
    op.create_index(
        "ix_observations_dedup",
        "observations",
        ["reporter_hash", "store_id", "product_category", "in_stock", "reported_at"],
    )

    op.create_table(
        "predictions",
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("product_category", product_category, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("n_observations", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "window_end > window_start",
            name="ck_predictions_window_order",
        ),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="ck_predictions_probability_range",
        ),
        sa.CheckConstraint(
            "n_observations >= 0",
            name="ck_predictions_n_observations",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_predictions_store_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("store_id", "product_category"),
    )


def downgrade() -> None:
    op.drop_table("predictions")
    op.drop_index("ix_observations_dedup", table_name="observations")
    op.drop_index("ix_observations_store_category_observed_at", table_name="observations")
    op.drop_table("observations")
    op.drop_table("sources")
    op.drop_table("stores")

    bind = op.get_bind()
    product_category.drop(bind, checkfirst=True)
    observation_kind.drop(bind, checkfirst=True)
    restock_regime.drop(bind, checkfirst=True)
    retailer.drop(bind, checkfirst=True)

"""Add report outcomes and report sources.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

report_outcome = postgresql.ENUM(
    "just_dropped",
    "in_stock",
    "sold_out",
    "nothing_here",
    name="report_outcome",
    create_type=False,
)
report_source = postgresql.ENUM(
    "dropdown",
    "freetext",
    "imported",
    name="report_source",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    report_outcome.create(bind, checkfirst=True)
    report_source.create(bind, checkfirst=True)

    op.add_column("observations", sa.Column("outcome", report_outcome, nullable=True))
    op.add_column("observations", sa.Column("quantity_note", sa.Text(), nullable=True))
    op.add_column("observations", sa.Column("raw_text", sa.Text(), nullable=True))
    op.add_column(
        "observations",
        sa.Column(
            "report_source",
            report_source,
            server_default="dropdown",
            nullable=False,
        ),
    )

    op.execute("UPDATE observations SET outcome = 'in_stock' WHERE kind = 'report'")

    op.drop_index("ix_observations_dedup", table_name="observations")
    op.create_index(
        "ix_observations_dedup",
        "observations",
        ["reporter_hash", "store_id", "outcome", "reported_at"],
    )
    op.create_index(
        "ix_observations_store_outcome_observed_at",
        "observations",
        ["store_id", "outcome", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_observations_store_outcome_observed_at", table_name="observations")
    op.drop_index("ix_observations_dedup", table_name="observations")
    op.create_index(
        "ix_observations_dedup",
        "observations",
        ["reporter_hash", "store_id", "product_category", "in_stock", "reported_at"],
    )

    op.drop_column("observations", "report_source")
    op.drop_column("observations", "raw_text")
    op.drop_column("observations", "quantity_note")
    op.drop_column("observations", "outcome")

    bind = op.get_bind()
    report_source.drop(bind, checkfirst=True)
    report_outcome.drop(bind, checkfirst=True)

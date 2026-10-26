"""Support the reviewed SWFL store list.

Adds GameStop and makes store coordinates optional because the reviewed list
contains addresses only. Coordinates remain paired: either both are set or
neither is.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE retailer ADD VALUE IF NOT EXISTS 'gamestop'")
    op.alter_column("stores", "lat", existing_type=sa.Float(), nullable=True)
    op.alter_column("stores", "lng", existing_type=sa.Float(), nullable=True)
    op.create_check_constraint(
        "ck_stores_coordinates_pair",
        "stores",
        "(lat IS NULL) = (lng IS NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    missing_coordinates = bind.scalar(
        sa.text("SELECT count(*) FROM stores WHERE lat IS NULL OR lng IS NULL")
    )
    if missing_coordinates:
        raise RuntimeError(
            "Cannot restore NOT NULL coordinates while stores without coordinates exist."
        )

    op.drop_constraint("ck_stores_coordinates_pair", "stores", type_="check")
    op.alter_column("stores", "lat", existing_type=sa.Float(), nullable=False)
    op.alter_column("stores", "lng", existing_type=sa.Float(), nullable=False)

    # PostgreSQL cannot remove enum values in place. Recreate the type so a
    # downgrade fails rather than silently losing data if GameStop is in use.
    op.execute("ALTER TYPE retailer RENAME TO retailer_old")
    op.execute(
        "CREATE TYPE retailer AS ENUM ("
        "'target', 'walmart', 'sams_club', 'costco', 'best_buy', "
        "'dollar_general', 'family_dollar', 'barnes_noble', "
        "'walgreens', 'cvs', 'ace_hardware', 'other'"
        ")"
    )
    op.execute(
        "ALTER TABLE stores ALTER COLUMN retailer TYPE retailer USING retailer::text::retailer"
    )
    op.execute("DROP TYPE retailer_old")

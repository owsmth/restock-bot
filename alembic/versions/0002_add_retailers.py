"""Add Family Dollar and Barnes & Noble retailers.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE retailer ADD VALUE IF NOT EXISTS 'family_dollar'")
    op.execute("ALTER TYPE retailer ADD VALUE IF NOT EXISTS 'barnes_noble'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values in place. Recreate the type so a
    # downgrade fails rather than silently losing data if either value is in use.
    op.execute("ALTER TYPE retailer RENAME TO retailer_old")
    op.execute(
        "CREATE TYPE retailer AS ENUM ("
        "'target', 'walmart', 'sams_club', 'costco', 'best_buy', "
        "'dollar_general', 'walgreens', 'cvs', 'ace_hardware', 'other'"
        ")"
    )
    op.execute(
        "ALTER TABLE stores ALTER COLUMN retailer TYPE retailer USING retailer::text::retailer"
    )
    op.execute("DROP TYPE retailer_old")

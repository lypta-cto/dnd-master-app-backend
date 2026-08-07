"""add slideshow cast mode

Revision ID: a1b2c3d4e5f6
Revises: be2995e09215
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "be2995e09215"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres 12+ allows this inside a transaction
    op.execute("ALTER TYPE cast_mode ADD VALUE IF NOT EXISTS 'slideshow'")


def downgrade() -> None:
    # Removing an enum value safely requires a type rebuild; not worth it here
    pass

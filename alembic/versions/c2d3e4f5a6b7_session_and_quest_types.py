"""session and quest entity types

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'session'")
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'quest'")


def downgrade() -> None:
    pass

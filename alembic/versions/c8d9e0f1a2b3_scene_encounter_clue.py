"""scene, encounter and clue types, and a leads_to relation

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'scene'")
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'encounter'")
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'clue'")
    # What turns a pile of scenes into a flowchart
    op.execute("ALTER TYPE link_relation ADD VALUE IF NOT EXISTS 'leads_to'")


def downgrade() -> None:
    pass

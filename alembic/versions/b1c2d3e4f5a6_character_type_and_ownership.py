"""character type and entity ownership

Revision ID: b1c2d3e4f5a6
Revises: 15abe83248a0
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "15abe83248a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'character'")
    op.add_column("entities", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_entities_owner_id"), "entities", ["owner_id"])
    op.create_foreign_key(
        "fk_entities_owner_id_users",
        "entities",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_entities_owner_id_users", "entities", type_="foreignkey")
    op.drop_index(op.f("ix_entities_owner_id"), table_name="entities")
    op.drop_column("entities", "owner_id")

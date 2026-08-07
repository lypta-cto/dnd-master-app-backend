"""monster type and combat state

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'monster'")
    op.create_table(
        "combat_states",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("combatants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_combat_states_campaign_id"), "combat_states", ["campaign_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_combat_states_campaign_id"), table_name="combat_states")
    op.drop_table("combat_states")

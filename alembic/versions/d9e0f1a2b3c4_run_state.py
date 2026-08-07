"""The evening in progress

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("active", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True)),
        sa.Column("revealed", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column("spotlight", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column("clock", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_run_states_campaign_id", "run_states", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_run_states_campaign_id", table_name="run_states")
    op.drop_table("run_states")

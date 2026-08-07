"""Players at the table, with or without an account

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("contact", sa.String(160)),
        sa.Column("experience", sa.String(20)),
        sa.Column(
            "preferences",
            postgresql.ARRAY(sa.String(20)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("notes", sa.String(1000)),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("invited_email", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_player_account_per_campaign"),
    )
    op.create_index("ix_players_campaign_id", "players", ["campaign_id"])
    op.create_index("ix_players_user_id", "players", ["user_id"])
    op.create_index("ix_players_invited_email", "players", ["invited_email"])

    op.add_column(
        "entities", sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_entities_player_id", "entities", "players", ["player_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_entities_player_id", "entities", ["player_id"])

    # Characters that already belong to an account get a seat, so nothing has to
    # be re-entered by hand: one player per (campaign, owner), named after the
    # account, already linked.
    op.execute(
        """
        INSERT INTO players (id, campaign_id, name, user_id, preferences, created_at, updated_at)
        SELECT DISTINCT ON (e.campaign_id, e.owner_id)
               gen_random_uuid(),
               e.campaign_id,
               COALESCE(NULLIF(u.full_name, ''), split_part(u.email, '@', 1)),
               e.owner_id,
               '{}',
               now(),
               now()
          FROM entities e
          JOIN users u ON u.id = e.owner_id
         WHERE e.type = 'character' AND e.owner_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE entities e
           SET player_id = p.id
          FROM players p
         WHERE p.campaign_id = e.campaign_id
           AND p.user_id = e.owner_id
           AND e.type = 'character'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_entities_player_id", table_name="entities")
    op.drop_constraint("fk_entities_player_id", "entities", type_="foreignkey")
    op.drop_column("entities", "player_id")

    op.drop_index("ix_players_invited_email", table_name="players")
    op.drop_index("ix_players_user_id", table_name="players")
    op.drop_index("ix_players_campaign_id", table_name="players")
    op.drop_table("players")
